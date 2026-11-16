"""Publish ICON-D2 temperatures on the original DWD regular grid in small tiles.

The matching hourly forecast supplies the run and horizon. Tiles never combine
different initializations or silently replace missing original values.
"""
import concurrent.futures as cf
import datetime as dt
import gzip
import json
import runpy
from pathlib import Path

import numpy as np

API = runpy.run_path(str(Path(__file__).with_name('ingest-icon.py')))
FIELDS = {'t_2m': 'temp2', 'tmin_2m': 'tmin', 'tmax_2m': 'tmax'}
SIZE = 100


def build(run, hours, offers):
    stamp = dt.datetime.fromisoformat(run).strftime('%Y%m%d%H')
    def read(task):
        var, hour = task
        url = offers[var].get((stamp, hour))
        if not url:
            if var == 't_2m': raise ValueError(f'Missing T_2M +{hour}')
            return None
        interval = None if var == 't_2m' else ((hour-1)//6*6, 'min' if var == 'tmin_2m' else 'max')
        try:
            x, y, values = API['sample_grib'](API['download'](url), None, None, stamp, hour, interval)
            # Crop to the app's ICON-D2 domain, retaining the original grid
            # (and one border cell for the nearest-cell lookup).
            west, east, south, north = API['MODELS']['icon-d2']['bounds']
            ix = np.flatnonzero((x>=west-.021)&(x<=east+.021))
            iy = np.flatnonzero((y>=south-.021)&(y<=north+.021))
            return hour, FIELDS[var], x[ix], y[iy], values[np.ix_(iy,ix)]-273.15
        except Exception:
            if var == 't_2m': raise
            return None

    tasks = [(v, h) for h in hours for v in FIELDS if h or v == 't_2m']
    tiles = {}; grid = None; axes = None
    with cf.ThreadPoolExecutor(max_workers=5) as pool:
        for result in pool.map(read, tasks):
            if result is None: continue
            h, field, x, y, values = result
            if grid is None:
                dx, dy = float(x[1]-x[0]), float(y[1]-y[0])
                if not (np.allclose(np.diff(x), dx, atol=1e-5) and np.allclose(np.diff(y), dy, atol=1e-5)):
                    raise ValueError('Irregular source coordinates')
                grid = dict(west=float(x[0]), south=float(y[0]), dx=dx, dy=dy, nx=len(x), ny=len(y), scale=.1, missing=-32768)
                axes = x, y
            if not (np.array_equal(x, axes[0]) and np.array_equal(y, axes[1])):
                raise ValueError('Inconsistent DWD temperature grids')
            for j in range(0, len(y), SIZE):
                for i in range(0, len(x), SIZE):
                    frames = tiles.setdefault(f'{i//SIZE}-{j//SIZE}', {})
                    frames.setdefault(str(h), {})[field] = API['pack'](values[j:j+SIZE, i:i+SIZE], .1)
    if not grid or not tiles: raise ValueError('No temperature data')
    return grid, tiles


def main():
    root = Path('data/icon-d2-temperature')
    root.mkdir(exist_ok=True)
    with gzip.open('data/icon-d2-hourly.json.gz', 'rt') as f: latest = json.load(f)['runs'][0]
    run, hours = latest['run'], latest['hours']
    manifest = root/'index.json'
    if manifest.exists():
        old = json.loads(manifest.read_text())
        if old['run'] == run and old['hours'] == hours: return
    cycle = dt.datetime.fromisoformat(run).strftime('%H')
    offers = {v: API['listing']('icon-d2', cycle, v) for v in FIELDS}
    grid, tiles = build(run, hours, offers)
    generated = dt.datetime.now(dt.timezone.utc).isoformat()
    metadata = dict(schema=1, model='ICON-D2', run=run, generated=generated, grid=grid, tileSize=SIZE, hours=hours, extremaWindowHours=6)
    for key, frames in tiles.items():
        path = root/(key+'.json.gz')
        packet = dict(schema=1, run=run, generated=generated, key=key, frames=frames)
        with gzip.open(path, 'wt', compresslevel=6) as f: json.dump(packet, f, separators=(',', ':'))
    manifest.write_text(json.dumps(metadata, separators=(',', ':')))
    print(f'Published {len(tiles)} native ICON-D2 temperature tiles for {run}', flush=True)


if __name__ == '__main__': main()
