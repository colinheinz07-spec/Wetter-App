"""Backfill WW for existing published model runs without replacing their grids."""
import concurrent.futures
import datetime as dt
import json
import runpy
from pathlib import Path

import numpy as np

api = runpy.run_path(str(Path(__file__).with_name('ingest-icon.py')))
out = Path('data/icon-weather.json')
previous = json.loads(out.read_text()) if out.exists() else {'schema': 1, 'models': {}}
models = dict(previous['models'])

for name, cfg in api['MODELS'].items():
    d = json.loads(Path(f'data/{name}.json').read_text())
    g = d['grid']
    needed = [h for h in d['hours'] if h and 'ww' not in d['frames'][str(h)]]
    if not needed:
        continue
    extra = models.get(cfg['name'], {})
    frames = dict(extra.get('frames', {})) if extra.get('run') == d['run'] and extra.get('grid') == g else {}
    needed = [h for h in needed if str(h) not in frames]
    if not needed:
        continue
    stamp = dt.datetime.fromisoformat(d['run']).strftime('%Y%m%d%H')
    try:
        offers = api['listing'](name, stamp[-2:], 'ww')
    except Exception as exc:
        print(f'{name}: WW unavailable: {exc}', flush=True)
        continue
    x = g['west'] + np.arange(g['nx']) * g['step']
    y = g['south'] + np.arange(g['ny']) * g['step']

    def get(hour):
        url = offers.get((stamp, hour))
        if not url:
            return hour, None
        try:
            return hour, api['pack'](api['sample_grib'](api['download'](url), x, y, stamp, hour), 1)
        except Exception as exc:
            print(f'{name} +{hour}: {exc}', flush=True)
            return hour, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for hour, packed in pool.map(get, needed):
            if packed is not None:
                frames[str(hour)] = packed
    if frames:
        models[cfg['name']] = dict(run=d['run'], grid=g, frames=frames)
    print(f'{name} {stamp}: {len(frames)} supplemental weather-code steps', flush=True)

payload = dict(schema=1, models=models)
if models and payload != previous:
    temporary = out.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, separators=(',', ':')))
    temporary.replace(out)
