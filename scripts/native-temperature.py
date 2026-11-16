"""Write verified temperature tiles for point forecasts and one independent map per lead time."""
import datetime as dt
import gzip
import json
from pathlib import Path
import numpy as np

SIZE=100

def grid_for(x,y):
    dx,dy=float(x[1]-x[0]),float(y[1]-y[0])
    if dx<=0 or dy<=0 or not np.allclose(np.diff(x),dx,atol=1e-5) or not np.allclose(np.diff(y),dy,atol=1e-5):
        raise ValueError('Source grid is not regularly spaced')
    return dict(west=float(x[0]),south=float(y[0]),dx=dx,dy=dy,nx=len(x),ny=len(y),scale=.1,missing=-32768)

def write_gzip(path,obj):
    with gzip.open(path,'wt',compresslevel=6) as f:json.dump(obj,f,separators=(',',':'))

def add_frame(tiles,grid,h,field,values,pack):
    if values.shape!=(grid['ny'],grid['nx']):raise ValueError('Source grid shape changed')
    if field=='temp2' and not np.isfinite(values).any():raise ValueError('Empty temperature field')
    for j in range(0,grid['ny'],SIZE):
        for i in range(0,grid['nx'],SIZE):
            tiles.setdefault(f'{i//SIZE}-{j//SIZE}',{}).setdefault(str(h),{})[field]=pack(values[j:j+SIZE,i:i+SIZE],.1)

def publish(root,model,run,hours,grid,tiles,maps,extrema=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    generated=dt.datetime.now(dt.timezone.utc).isoformat()
    meta=dict(schema=1,model=model,run=run,generated=generated,grid=grid,tileSize=SIZE,hours=hours,mapHours=sorted(maps),extremaWindowHours=extrema)
    for key,frames in tiles.items():
        if not all('temp2' in frames.get(str(h),{}) for h in hours):raise ValueError('Incomplete temperature tile')
        write_gzip(root/(key+'.json.gz'),dict(schema=1,run=run,generated=generated,key=key,frames=frames))
    for h,packed in maps.items():
        write_gzip(root/(f'map-{h}.json.gz'),dict(schema=1,run=run,generated=generated,hour=h,temp2=packed))
    (root/'index.json').write_text(json.dumps(meta,separators=(',',':')))
    print(f'{model}: {len(tiles)} tiles, {len(maps)} original-grid map steps, {run}',flush=True)

def already(root,run,hours):
    p=Path(root)/'index.json'
    if not p.exists():return False
    m=json.loads(p.read_text())
    return m['run']==run and m['hours']==hours and m.get('mapHours')==hours
