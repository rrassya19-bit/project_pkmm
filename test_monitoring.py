import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from monitoring import Monitor, grid_points, priorities, historical_potential
import server

UTC=timezone.utc

def result(now=None, label='1', score=.8):
    return dict(label=label, classes=['0','1'], probabilities=[1-score,score], scene={'id':'test-scene','datetime':(now or datetime.now(UTC)).isoformat()})

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.calls=[]
        def analyze(lon,lat,start,end):
            self.calls.append((lon,lat))
            return result()
        self.monitor=Monitor(Path(self.temp.name)/'monitor.json',analyze,lambda lon,lat:True)
    def tearDown(self):
        self.temp.cleanup()
    def configure(self):
        return self.monitor.configure([113,-3,114,-2],30)
    def test_grid_and_limits(self):
        self.assertEqual(len(grid_points([113,-3,114,-2],lambda x,y:True)),9)
        self.assertEqual(len(grid_points([113,-3,114,-2],lambda x,y:x<113.5)),3)
        for box in ([94,-12,142,7],[113,-3,113,-2],[float('nan'),-3,114,-2]):
            with self.assertRaises(ValueError):grid_points(box,lambda x,y:True)
        with self.assertRaises(ValueError):grid_points([113,-3,114,-2],lambda x,y:False)
    def test_bounded_round_robin_and_persistence(self):
        self.configure();self.monitor.run_cycle()
        state=self.monitor.snapshot()
        self.assertEqual(len(self.calls),5)
        self.assertEqual(sum(p['status']=='ok' for p in state['points']),5)
        self.assertGreater(state['next_at'],0)
        self.monitor.run_cycle()
        self.assertEqual(len(set(self.calls)),9)
        loaded=Monitor(self.monitor.path,self.monitor.analyze,self.monitor.on_land)
        self.assertEqual(loaded.snapshot()['cursor'],1)
        self.assertEqual(sum(p['status']=='ok' for p in loaded.snapshot()['points']),9)
    def test_failure_does_not_stop_other_points(self):
        self.configure()
        def analyze(*args):
            self.calls.append(args)
            if len(self.calls)==1:raise ValueError('Piksel tertutup awan')
            return result()
        self.monitor.analyze=analyze;self.monitor.run_cycle()
        self.assertEqual(self.monitor.snapshot()['points'][0]['status'],'error')
        self.assertEqual(len(self.calls),5)
        self.assertFalse(self.monitor.busy)
    def test_pause_stops_after_current_and_no_overlap(self):
        self.configure()
        def analyze(*args):
            self.calls.append(args)
            self.monitor.run_cycle()
            self.monitor.control('pause')
            return result()
        self.monitor.analyze=analyze;self.monitor.run_cycle()
        self.assertEqual(len(self.calls),1)
        self.assertFalse(self.monitor.snapshot()['enabled'])
        self.monitor.run_cycle();self.assertEqual(len(self.calls),1)
    def test_rank_active_then_potential_and_ignore_stale(self):
        now=datetime.now(UTC)
        def hotspot(lat,age):
            t=now-timedelta(hours=age)
            return dict(lat=lat,lon=114,confidence='h',frp=10,date=t.strftime('%Y-%m-%d'),time=t.strftime('%H%M'))
        def point(lat,age,label='1',status='ok'):
            return dict(lat=lat,lon=114,status=status,result=result(now-timedelta(days=age),label))
        rows=priorities([hotspot(-2,1),hotspot(-2.1,25)],[point(-3,1),point(-4,15),point(-5,1,'0'),point(-6,1,status='error'),point(-2,1)],now)
        self.assertEqual([r['tier'] for r in rows],[1,2])
        self.assertEqual(rows[1]['lat'],-3)
    def test_old_class_one_is_visible_but_not_current_priority(self):
        now=datetime.now(UTC)
        point=dict(lat=-3,lon=114,status='ok',result=result(now-timedelta(days=15)))
        self.assertEqual(priorities([], [point], now), [])
        history=historical_potential([point], now)
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]['age_days'],15)
        self.assertEqual(history[0]['score'],.8)
        point['result']=result(now-timedelta(days=1))
        self.assertEqual(historical_potential([point],now),[])

    def test_monitor_api(self):
        with patch.object(server,'MONITOR',self.monitor):
            client=server.app.test_client()
            self.assertEqual(client.post('/api/monitor',json={'action':'run'}).status_code,400)
            response=client.post('/api/monitor',json={'action':'configure','bbox':[113,-3,114,-2],'interval_minutes':30})
            self.assertEqual(response.status_code,200)
            self.assertEqual(len(response.get_json()['points']),9)
            self.assertEqual(client.get('/api/monitor').status_code,200)
            with patch('server.fetch_hotspots',return_value=dict(points=[],retrieved_at=None)):
                self.assertEqual(client.get('/api/priorities').status_code,200)
            self.assertEqual(client.post('/api/monitor',json={'action':'pause'}).status_code,200)
    def test_manual_prediction_uses_shared_pipeline(self):
        values=dict(B2=500,B3=674,B4=386,B8=4344,B11=1848,B12=755)
        scene=dict(id='mock-scene',datetime=datetime.now(UTC).isoformat(),cloud=10)
        with patch('server.scene',return_value=(values,scene)):
            response=server.app.test_client().post('/api/predict',json={'lon':116.3,'lat':-8.5,'start':'2025-08-01','end':'2025-08-31'})
        self.assertEqual(response.status_code,200)
        self.assertIn(response.get_json()['label'],['0','1'])
    def test_scene_cache_reuses_bands(self):
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'features':[dict(id='cache-test',properties={'datetime':'2025-08-01T00:00:00Z'})]}
        server.CACHE.pop(('sentinel',116,-8,'cache-test'),None)
        with patch.object(server.SESSION,'post',return_value=Response()),patch('server.extract_scene',return_value={'B2':500}) as read:
            first,_=server.scene(116,-8,'2025-08-01','2025-08-31')
            first['NDVI']=0
            second,_=server.scene(116,-8,'2025-08-01','2025-08-31')
        self.assertEqual(read.call_count,1)
        self.assertNotIn('NDVI',second)
        server.CACHE.pop(('sentinel',116,-8,'cache-test'),None)

if __name__=='__main__':unittest.main()
