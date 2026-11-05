from pathlib import Path
import os, io, csv, time, math, threading
from datetime import datetime, timedelta, timezone
import joblib, pandas as pd, requests
from flask import Flask, request, jsonify, send_from_directory

ROOT = Path(__file__).resolve().parent
for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines() if (ROOT / '.env').exists() else []:
    if '=' in line and not line.lstrip().startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip(chr(34)).strip(chr(39)))
app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
BUNDLE = joblib.load(ROOT / 'model_early_warning_sentinel2.joblib')
MODEL = BUNDLE['model'] if isinstance(BUNDLE, dict) else BUNDLE
FEATURES = list(BUNDLE.get('features', MODEL.feature_names_)) if isinstance(BUNDLE, dict) else list(MODEL.feature_names_)
CACHE = {}
SESSION = requests.Session()
ANALYSIS_LOCK = threading.Lock()

def http(url, **kwargs):
    r = SESSION.get(url, timeout=45, **kwargs)
    r.raise_for_status()
    return r

def boundary():
    if 'boundary' not in CACHE:
        saved = ROOT / 'indonesia.geojson'
        if saved.exists():
            import json
            CACHE['boundary'] = json.loads(saved.read_text(encoding='utf-8'))
            return CACHE['boundary']
        geo = http('https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson').json()
        country = next(f for f in geo['features'] if f['properties'].get('ISO3166-1-Alpha-3') == 'IDN' or f['properties'].get('name') == 'Indonesia')
        CACHE['boundary'] = country
    return CACHE['boundary']

def in_ring(x, y, ring):
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside

def indonesia(lon, lat):
    geo = boundary()['geometry']
    polygons = geo['coordinates'] if geo['type'] == 'MultiPolygon' else [geo['coordinates']]
    return any(in_ring(lon, lat, p[0]) and not any(in_ring(lon, lat, hole) for hole in p[1:]) for p in polygons)

@app.errorhandler(Exception)
def error(exc):
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        return jsonify(error=exc.description), exc.code
    app.logger.warning('%s: %s', type(exc).__name__, str(exc).replace(os.getenv('FIRMS_MAP_KEY') or '__NO_KEY__', '[KEY]'))
    messages = {ValueError: str(exc), requests.Timeout: 'Layanan satelit melewati batas waktu. Coba kembali.'}
    return jsonify(error=messages.get(type(exc), 'Data belum dapat diproses. Periksa koneksi dan log server.')), 400 if isinstance(exc, ValueError) else 502

@app.get('/')
def home():
    return send_from_directory(ROOT / 'static', 'index.html')

@app.get('/api/status')
def status():
    return jsonify(model=type(MODEL).__name__, features=FEATURES, classes=[str(x) for x in getattr(MODEL, 'classes_', [])], firms_configured=bool(os.getenv('FIRMS_MAP_KEY')))

@app.get('/api/boundary')
def borders():
    return jsonify(boundary())

def fetch_hotspots(days):
    key = os.getenv('FIRMS_MAP_KEY', '')
    if not key:
        raise ValueError('NASA FIRMS MAP_KEY belum diisi. Ikuti PETUNJUK.md, lalu restart server.')
    if days not in (1, 2, 3):
        raise ValueError('Rentang waktu harus 1–3 hari.')
    cached = CACHE.get(('firms', days))
    if cached and time.time() - cached[0] < 300:
        return cached[1]
    # Fetch the Indonesian bounding box, then exclude neighbouring countries below.
    url = f'https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/94,-12,142,7/{days}'
    try:
        raw = http(url).text
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 'unknown'
        raise ValueError(f'NASA FIRMS menolak permintaan (HTTP {code}). Periksa MAP_KEY dan kuota API.') from None
    rows = list(csv.DictReader(io.StringIO(raw)))
    if 'latitude' not in (rows[0] if rows else raw.partition('\n')[0]):
        raise ValueError('Respons FIRMS tidak valid. Periksa MAP_KEY dan kuota NASA FIRMS.')
    points = []
    for row in rows:
        lat, lon = float(row['latitude']), float(row['longitude'])
        if indonesia(lon, lat):
            points.append(dict(lat=lat, lon=lon, confidence=row.get('confidence'), frp=float(row.get('frp') or 0), date=row.get('acq_date'), time=row.get('acq_time', '').zfill(4), satellite=row.get('satellite'), daynight=row.get('daynight')))
    result = dict(points=points, retrieved_at=datetime.now(timezone.utc).isoformat(), source='NASA FIRMS • VIIRS S-NPP NRT', days=days)
    CACHE[('firms', days)] = time.time(), result
    return result

@app.get('/api/hotspots')
def hotspots():
    return jsonify(fetch_hotspots(int(request.args.get('days', 1))))

def extract_scene(item, lon, lat):
    import importlib.util
    spec = importlib.util.find_spec('rasterio')
    # Keep GDAL isolated from the PostgreSQL/PostGIS PROJ database on this machine.
    os.environ['PROJ_DATA'] = str(Path(spec.origin).parent / 'proj_data')
    os.environ['PROJ_LIB'] = os.environ['PROJ_DATA']
    import rasterio
    from rasterio.warp import transform
    aliases = {'B2':'blue', 'B3':'green', 'B4':'red', 'B8':'nir', 'B11':'swir16', 'B12':'swir22'}
    values = {}
    assets = item['assets']
    scl = assets.get('scl')
    if not scl:
        raise ValueError('Masker awan SCL tidak tersedia; prediksi dibatalkan.')
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_TIMEOUT='35', AWS_NO_SIGN_REQUEST='YES'):
        with rasterio.open(scl['href']) as src:
            xs, ys = transform('EPSG:4326', src.crs, [lon], [lat])
            quality = int(next(src.sample([(xs[0], ys[0])]))[0])
    if quality in (0, 1, 3, 8, 9, 10, 11):
        raise ValueError('Piksel tertutup awan/bayangan atau tidak valid. Pilih tanggal atau lokasi lain.')
    for band, alias in aliases.items():
        asset = assets.get(alias) or assets.get(band)
        if not asset:
            raise ValueError(f'Kanal {band} tidak tersedia pada citra.')
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_TIMEOUT='35', AWS_NO_SIGN_REQUEST='YES'):
            with rasterio.open(asset['href']) as src:
                xs, ys = transform('EPSG:4326', src.crs, [lon], [lat])
                val = float(next(src.sample([(xs[0], ys[0])]))[0])
                if val == src.nodata or not math.isfinite(val) or val <= 0:
                    raise ValueError('Piksel kosong atau tidak valid. Pilih titik atau tanggal lain.')
                # Earth Search COGs store DN; retain the model training scale (0–10000).
                meta = asset.get('raster:bands', [{}])[0]
                scale, offset = meta.get('scale', 0.0001), meta.get('offset', 0)
                if item['properties'].get('earthsearch:boa_offset_applied'):
                    offset = 0
                values[band] = (val * scale + offset) * 10000
    return values

def scene(lon, lat, start, end):
    body = {'collections':['sentinel-2-l2a'], 'intersects':{'type':'Point','coordinates':[lon,lat]}, 'datetime':f'{start}T00:00:00Z/{end}T23:59:59Z', 'query':{'eo:cloud_cover':{'lt':40}}, 'limit':40, 'sortby':[{'field':'properties.datetime','direction':'desc'}]}
    r = SESSION.post('https://earth-search.aws.element84.com/v1/search', json=body, timeout=45)
    r.raise_for_status()
    items = r.json().get('features', [])
    if not items:
        raise ValueError('Tidak ada citra Sentinel-2 dengan awan scene <40% pada rentang tanggal tersebut.')
    errors = []
    for item in sorted(items, key=lambda i:i['properties']['datetime'], reverse=True)[:5]:
        try:
            cache_key = ('sentinel', lon, lat, item['id'])
            if cache_key not in CACHE:
                values = extract_scene(item, lon, lat)
                keys = [k for k in list(CACHE) if isinstance(k, tuple) and k[0] == 'sentinel']
                if len(keys) >= 128:
                    CACHE.pop(keys[0], None)
                CACHE[cache_key] = values
            return dict(CACHE[cache_key]), dict(id=item['id'], datetime=item['properties']['datetime'], cloud=item['properties'].get('eo:cloud_cover'))
        except ValueError as exc:
            errors.append(str(exc))
    raise ValueError('Lima citra terbaru tidak memiliki piksel layak: ' + errors[-1])

def predict(values):
    missing = [f for f in FEATURES if f not in values]
    if missing:
        raise ValueError('Fitur model belum dapat dihitung otomatis: ' + ', '.join(missing))
    frame = pd.DataFrame([[values[f] for f in FEATURES]], columns=FEATURES)
    label = str(MODEL.predict(frame).reshape(-1)[0])
    probabilities = MODEL.predict_proba(frame)[0].tolist() if hasattr(MODEL,'predict_proba') else None
    return dict(label=label, probabilities=probabilities, classes=[str(x) for x in getattr(MODEL,'classes_',[])], features=values)

def analyze_location(lon, lat, start, end):
    with ANALYSIS_LOCK:
        return analyze_unlocked(lon, lat, start, end)

def analyze_unlocked(lon, lat, start, end):
    values, current = scene(lon, lat, start.isoformat(), end.isoformat())
    values['longitude'], values['latitude'] = lon, lat
    values['NDVI'] = (values['B8']-values['B4'])/(values['B8']+values['B4'])
    mode = os.getenv('NDWI_FORMULA', 'green_nir')
    if mode not in ('green_nir', 'nir_swir'):
        raise ValueError('NDWI_FORMULA harus green_nir atau nir_swir.')
    a, b = (values['B3'], values['B8']) if mode == 'green_nir' else (values['B8'], values['B11'])
    values['NDWI'] = (a-b)/(a+b)
    baseline = None
    if 'dNBR' in FEATURES:
        before_end = start - timedelta(days=1)
        previous, baseline = scene(lon, lat, (before_end-timedelta(days=60)).isoformat(), before_end.isoformat())
        nbr = lambda v:(v['B8']-v['B12'])/(v['B8']+v['B12'])
        values['dNBR'] = nbr(previous)-nbr(values)
    result = predict(values)
    result.update(lon=lon, lat=lat, scene=current, baseline=baseline, warning='Kelas 1 = berpotensi terbakar; kelas 0 = aman menurut model (sesuai keterangan pemilik model). Formula NDWI dan kalibrasi skor perlu dicocokkan dengan pelatihan. Hasil bukan konfirmasi kebakaran atau jaminan keamanan.')
    return result

@app.post('/api/predict')
def prediction():
    data = request.get_json() or {}
    if not all(k in data for k in ('lon', 'lat', 'start', 'end')):
        raise ValueError('Koordinat dan tanggal wajib diisi.')
    lon, lat = float(data['lon']), float(data['lat'])
    if not math.isfinite(lon) or not math.isfinite(lat) or not indonesia(lon, lat):
        raise ValueError('Pilih titik daratan di dalam wilayah Indonesia.')
    end = datetime.strptime(data['end'], '%Y-%m-%d').date()
    start = datetime.strptime(data['start'], '%Y-%m-%d').date()
    if start > end or (end-start).days > 90 or end > datetime.now(timezone.utc).date():
        raise ValueError('Rentang tanggal harus 0–90 hari dan tidak boleh di masa depan.')
    return jsonify(analyze_location(lon, lat, start, end))

from monitoring import Monitor, priorities, historical_potential
MONITOR = Monitor(ROOT / 'monitor_state.json', analyze_location, indonesia)

@app.get('/api/monitor')
def monitor_status():
    return jsonify(MONITOR.snapshot())

@app.post('/api/monitor')
def monitor_control():
    data = request.get_json() or {}
    if data.get('action') == 'configure':
        return jsonify(MONITOR.configure(data.get('bbox'), data.get('interval_minutes', 30)))
    return jsonify(MONITOR.control(data.get('action')))

@app.get('/api/priorities')
def priority_list():
    warning = None
    try:
        firms = fetch_hotspots(1)
    except (ValueError, requests.RequestException):
        cached = CACHE.get(('firms', 1))
        firms = cached[1] if cached else dict(points=[], retrieved_at=None)
        warning = 'FIRMS belum dapat diperbarui. Daftar ini belum lengkap; bukan berarti tidak ada kebakaran.'
    state = MONITOR.snapshot()
    rows = priorities(firms['points'], state['points'])
    return jsonify(rows=rows, historical_potential=historical_potential(state['points']), active_count=sum(r['tier']==1 for r in rows), potential_count=sum(r['tier']==2 for r in rows),
                   firms_updated_at=firms['retrieved_at'], warning=warning,
                   note='Prioritas 1: deteksi termal dalam 24 jam, belum konfirmasi lapangan. Prioritas 2: kelas 1 CatBoost dengan citra maksimal 14 hari. Sampel grid bukan peta risiko seluruh area.')

if __name__ == '__main__':
    MONITOR.start_worker()
    print('Buka http://127.0.0.1:5000 • fitur model:', FEATURES)
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
