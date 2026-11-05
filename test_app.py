import os
import unittest
from unittest.mock import patch
import server

class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_page_and_status(self):
        with self.client.get('/') as response:
            self.assertEqual(response.status_code, 200)
        data = self.client.get('/api/status').get_json()
        self.assertEqual(len(data['features']), 10)
        self.assertIn('NDWI', data['features'])

    def test_missing_key_is_explicit(self):
        with patch.dict(os.environ, {'FIRMS_MAP_KEY': ''}):
            r = self.client.get('/api/hotspots')
        self.assertEqual(r.status_code, 400)
        self.assertIn('MAP_KEY', r.get_json()['error'])

    def test_indonesia_boundary(self):
        self.assertTrue(server.indonesia(113.9, -2.2))
        self.assertFalse(server.indonesia(103.82, 1.35))
        self.assertFalse(server.indonesia(0, 0))

    def test_reject_foreign_location(self):
        r = self.client.post('/api/predict', json={'lon':0,'lat':0,'start':'2025-01-01','end':'2025-01-02'})
        self.assertEqual(r.status_code, 400)

    def test_reject_missing_fields(self):
        self.assertEqual(self.client.post('/api/predict', json={}).status_code, 400)

    def test_actual_model_inference(self):
        values = dict(B2=635.5,B3=692,B4=790.5,B8=1325.5,B11=2117.5,B12=1728,NDVI=(1325.5-790.5)/(1325.5+790.5),NDWI=(692-1325.5)/(692+1325.5),longitude=111.8561,latitude=-3.4548)
        result = server.predict(values)
        self.assertIn(result['label'], result['classes'])
        self.assertAlmostEqual(sum(result['probabilities']), 1, places=6)
        self.assertEqual(len(result['probabilities']), 2)

    def test_firms_response(self):
        class Response:
            text = 'latitude,longitude,confidence,frp,acq_date,acq_time,satellite\n-2.2,113.9,h,12.5,2025-01-01,0030,N\n1.35,103.82,h,5,2025-01-01,0030,N\n'
        server.CACHE.pop(('firms', 1), None)
        with patch.dict(os.environ, {'FIRMS_MAP_KEY':'test'}), patch('server.http', return_value=Response()) as fetch:
            r=self.client.get('/api/hotspots?days=1')
        fetch.assert_called_once_with('https://firms.modaps.eosdis.nasa.gov/api/area/csv/test/VIIRS_SNPP_NRT/94,-12,142,7/1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()['points']),1)
        server.CACHE.pop(('firms', 1), None)

if __name__ == '__main__':
    unittest.main()
