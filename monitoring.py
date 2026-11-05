"""Bounded, persistent Sentinel-2 monitoring and response-priority ordering."""
import copy
import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc

def timestamp():
    return datetime.now(UTC).isoformat()

def grid_points(bbox, on_land):
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError('Pilih dua sudut area pada peta terlebih dahulu.')
    west, south, east, north = map(float, bbox)
    if not all(math.isfinite(v) for v in (west, south, east, north)):
        raise ValueError('Koordinat area tidak valid.')
    if not (94 <= west < east <= 142 and -12 <= south < north <= 7):
        raise ValueError('Area harus berada di sekitar wilayah Indonesia.')
    if east-west > 2 or north-south > 2 or east-west < .005 or north-south < .005:
        raise ValueError('Lebar dan tinggi area harus 0,005 sampai 2 derajat (maksimal sekitar 220 km). Perbesar zoom peta.')
    points = []
    for row in range(3):
        for col in range(3):
            lon = west + (col+.5)*(east-west)/3
            lat = south + (row+.5)*(north-south)/3
            if on_land(lon, lat):
                points.append(dict(id=f'{row+1}-{col+1}', lat=lat, lon=lon, status='pending', result=None, error=None, checked_at=None))
    if not points:
        raise ValueError('Tidak ada pusat grid di daratan Indonesia. Pilih area lebih kecil di daratan.')
    return points

class Monitor:
    def __init__(self, path, analyze, on_land):
        self.path = Path(path)
        self.analyze = analyze
        self.on_land = on_land
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.thread = None
        self.busy = False
        self.current = None
        self.state = dict(enabled=False, interval_minutes=30, bbox=None, points=[], cursor=0, last_run=None, next_at=0)
        if self.path.exists():
            self.state.update(json.loads(self.path.read_text(encoding='utf-8')))
            for point in self.state['points']:
                if point['status'] == 'running':
                    point['status'] = 'pending'

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        temporary.replace(self.path)

    def snapshot(self):
        with self.lock:
            state = copy.deepcopy(self.state)
            state.update(busy=self.busy, current=self.current, batch_size=5, grid_size=3,
                         next_run=datetime.fromtimestamp(state['next_at'], UTC).isoformat() if state['enabled'] and state['next_at'] else None)
            return state

    def configure(self, bbox, interval):
        if interval not in (30, 60, 180):
            raise ValueError('Interval harus 30, 60, atau 180 menit.')
        points = grid_points(bbox, self.on_land)
        with self.lock:
            if self.busy:
                raise ValueError('Siklus masih berjalan. Jeda pemantauan, lalu tunggu titik saat ini selesai sebelum mengganti area.')
            self.state.update(bbox=bbox, points=points, interval_minutes=interval, cursor=0, enabled=True, next_at=0, last_run=None)
            self.save()
        self.wake.set()
        return self.snapshot()

    def control(self, action):
        with self.lock:
            if action not in ('start', 'pause', 'run'):
                raise ValueError('Aksi pemantauan tidak dikenal.')
            if action != 'pause' and not self.state['points']:
                raise ValueError('Pilih dan simpan area pemantauan terlebih dahulu.')
            if action == 'run' and self.busy:
                raise ValueError('Siklus sedang berjalan. Tidak perlu memulai lagi.')
            self.state['enabled'] = action != 'pause'
            if action != 'pause':
                self.state['next_at'] = 0
            self.save()
        self.wake.set()
        return self.snapshot()

    def run_cycle(self):
        with self.lock:
            if self.busy or not self.state['enabled'] or not self.state['points']:
                return
            self.busy = True
            count = min(5, len(self.state['points']))
        try:
            for _ in range(count):
                with self.lock:
                    if not self.state['enabled']:
                        break
                    index = self.state['cursor'] % len(self.state['points'])
                    point = self.state['points'][index]
                    point.update(status='running', error=None)
                    self.current = point['id']
                    lon, lat = point['lon'], point['lat']
                end = datetime.now(UTC).date()
                try:
                    result = self.analyze(lon, lat, end-timedelta(days=30), end)
                    update = dict(status='ok', result=result, error=None, checked_at=timestamp())
                except Exception as exc:
                    # Do not persist request URLs or credentials from external-service exceptions.
                    message = str(exc) if isinstance(exc, ValueError) else 'Layanan citra belum berhasil dibaca. Coba pada siklus berikutnya; lihat log server.'
                    update = dict(status='error', error=message, checked_at=timestamp())
                with self.lock:
                    point.update(update)
                    self.state['cursor'] = (index+1) % len(self.state['points'])
                    self.save()
        finally:
            with self.lock:
                self.busy = False
                self.current = None
                self.state.update(last_run=timestamp(), next_at=time.time()+self.state['interval_minutes']*60)
                self.save()

    def start_worker(self):
        if self.thread and self.thread.is_alive():
            return
        def work():
            while True:
                self.wake.clear()
                try:
                    with self.lock:
                        due = self.state['enabled'] and self.state['points'] and time.time() >= self.state['next_at']
                    if due:
                        self.run_cycle()
                except Exception:
                    import logging
                    logging.exception('Monitoring worker failed; retrying in 10 seconds')
                self.wake.wait(10)
        self.thread = threading.Thread(target=work, name='sentinel-monitor', daemon=True)
        self.thread.start()

def priorities(hotspots, points, now=None):
    now = now or datetime.now(UTC)
    active = []
    for point in hotspots:
        try:
            acquired = datetime.strptime(point['date']+point['time'].zfill(4), '%Y-%m-%d%H%M').replace(tzinfo=UTC)
        except (ValueError, TypeError, KeyError):
            continue
        if not timedelta(0) <= now-acquired <= timedelta(hours=24):
            continue
        active.append(dict(tier=1, category='Indikasi kebakaran aktif', lat=point['lat'], lon=point['lon'],
                           observed_at=acquired.isoformat(), confidence=point['confidence'], frp=point['frp'],
                           source='NASA FIRMS / VIIRS', score=None, reason='Deteksi termal 24 jam terakhir; perlu konfirmasi lapangan.'))
    active.sort(key=lambda p: (p['observed_at'][:10], {'h':2,'n':1,'l':0}.get(p['confidence'],0), p['frp'], p['observed_at']), reverse=True)
    potential = []
    for point in points:
        result = point.get('result')
        if point['status'] not in ('ok', 'running') or not result or result.get('label') != '1':
            continue
        acquired = datetime.fromisoformat(result['scene']['datetime'].replace('Z', '+00:00'))
        if not timedelta(0) <= now-acquired <= timedelta(days=14):
            continue
        score = result['probabilities'][result['classes'].index('1')]
        # Suppress duplicate prevention entries within 1 km of a recent thermal detection.
        if any(math.hypot((p['lon']-point['lon'])*math.cos(math.radians(point['lat'])), p['lat']-point['lat'])*111 < 1 for p in active):
            continue
        potential.append(dict(tier=2, category='Berpotensi terbakar', lat=point['lat'], lon=point['lon'],
                              observed_at=acquired.isoformat(), confidence=None, frp=None, source='Sentinel-2 / XGBoost',
                              score=score, reason='Kelas 1: prioritas pencegahan; skor model bukan kepastian kejadian.'))
    potential.sort(key=lambda p:(p['score'],p['observed_at']), reverse=True)
    return active+potential


def historical_potential(points, now=None):
    """Keep older class-1 results visible without promoting them to current alerts."""
    now = now or datetime.now(UTC)
    rows = []
    for point in points:
        result = point.get('result')
        if point['status'] not in ('ok', 'running') or not result or result.get('label') != '1':
            continue
        acquired = datetime.fromisoformat(result['scene']['datetime'].replace('Z', '+00:00'))
        age = now-acquired
        if age <= timedelta(days=14):
            continue
        rows.append(dict(tier=3, category='Kelas 1 - citra lama', lat=point['lat'], lon=point['lon'],
                         observed_at=acquired.isoformat(), age_days=age.days,
                         score=result['probabilities'][result['classes'].index('1')],
                         reason='Perlu citra baru dan analisis ulang; tidak dihitung sebagai prioritas potensi terbaru.'))
    return sorted(rows, key=lambda p:(p['observed_at'],p['score']), reverse=True)
