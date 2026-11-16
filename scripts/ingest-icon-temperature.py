"""Publish ICON-D2 and ICON-EU temperatures on the original DWD regular grid in small tiles.

The matching hourly forecast supplies the run and horizon. Tiles never combine
different initializations or silently replace missing original values.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import gzip
import json
import runpy
from pathlib import Path

import numpy as np

API = runpy.run_path(str(Path(__file__).with_name('ingest-icon.py')))
FIELDS = {'t_2m': 'temp2', 'tmin_2m': 'tmin', 'tmax_2m': 'tmax'}
NATIVE = runpy.run_path(str(Path(__file__).with_name('native-temperature.py')))
SIZE = NATIVE['SIZE']


def build(run, hours, offers, model="icon-d2"):
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
            west, east, south, north = API['MODELS'][model]['bounds']
            ix = np.flatnonzero((x>=west-1.01*abs(x[1]-x[0]))&(x<=east+1.01*abs(x[1]-x[0])))
            iy = np.flatnonzero((y>=south-1.01*abs(y[1]-y[0]))&(y<=north+1.01*abs(y[1]-y[0])))
            return hour, FIELDS[var], x[ix], y[iy], values[np.ix_(iy,ix)]-273.15
        except Exception:
            if var == 't_2m': raise
            return None

    tasks = [(v, h) for h in hours for v in FIELDS if h or v == 't_2m']
    tiles = {}; maps = {}; grid = None; axes = None
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
            NATIVE['add_frame'](tiles,grid,h,field,values,API['pack'])
            if field=='temp2':maps[h]=API['pack'](values,.1)
    if not grid or not tiles: raise ValueError('No temperature data')
    return grid, tiles, maps


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',choices=API['MODELS'],default='icon-d2')
    parser.add_argument('--map',action='store_true')
    args=parser.parse_args()
    model=args.model
    if args.map:
        runs=[json.loads(Path(f'data/{model}.json').read_text())]
    else:
        with gzip.open(f'data/{model}-hourly.json.gz','rt') as f:runs=json.load(f)['runs']
    for i,latest in enumerate(runs):
        suffix='-map-temperature' if args.map else '-anchor-temperature' if i else '-temperature'
        root=Path('data')/(model+suffix)
        run,hours=latest['run'],latest['hours']
        if NATIVE['already'](root,run,hours):continue
        cycle=dt.datetime.fromisoformat(run).strftime('%H')
        try:
            offers={v:API['listing'](model,cycle,v) for v in FIELDS}
            grid,tiles,maps=build(run,hours,offers,model)
            NATIVE['publish'](root,latest['model'],run,hours,grid,tiles,maps,6)
        except Exception as e:
            if i==0:raise
            print(f'Anchor temperature data unavailable: {e}',flush=True)

if __name__=='__main__':main()
