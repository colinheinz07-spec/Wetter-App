"""Small native-grid forecast tiles for location requests, not map rendering.

Each tile contains every forecast step on exactly the published grid. Temporary
per-tile streams bound memory; no national forecast raster is sent to a phone.
"""
import base64
import gzip
import json
from pathlib import Path
import tempfile
import numpy as np

CORE = {'temp2', 'dew', 'wind', 'slp', 'cloud', 'rainTotal'}
SURFACE = CORE | {'winddir', 'gust', 'rh2', 'visibility', 'ww', 'ptype','orog','ps','u10','v10',
    'lowcloud', 'midcloud', 'highcloud', 'tground', 'ground', 'snowdepth',
    'tmin', 'tmax', 'tsnow', 'snowline', 'freezing', 'mlcape', 'mlcin',
    'cape', 'cin', 'mucape', 'mucin', 'pwat', 'convTotal', 'solarTotal',
    'cloudbase', 'cloudtop', 'deepcloudtop', 's01', 's03', 's06', 'srh01',
    'srh03', 'lcl', 'lfc', 'el', 'dcape', 'thetae', 'lapse', 'lapse7',
    't850', 't700', 't500', 'rh850', 'rh700', 'rh500', 'z850', 'z700', 'z500',
    'u850', 'v850', 'u700', 'v700', 'u500', 'v500', 'snownew', 'wind100',
    'sunhours', 'uv', 'pop', 'li', 'stp', 'scp', 'hail', 'downburst'} | {
    f'{field}{level}' for field in ('t','rh','z','u','v')
    for level in (1000,975,950,925,900,850,800,700,600,500,400,300,250,200,150,100)}

class PointTiles:
    def __init__(self, output, model, run, generated, hours, size=24, extrema=None):
        self.output=Path(output); self.output.mkdir(parents=True, exist_ok=True)
        self.meta=dict(schema=3,model=model,run=run,generated=generated,hours=hours,
                       tileSize=size,scales={},frames={},extremaWindowHours=extrema)
        self.temp=tempfile.TemporaryDirectory(prefix='weather-point-')
        self.keys=set()

    def add(self, grid, hour, packed, scales):
        if self.meta.get('grid',grid)!=grid: raise ValueError('Point grid changed')
        self.meta['grid']=grid
        if not CORE<=packed.keys(): raise ValueError('Missing point core field')
        shape=(grid['ny'],grid['nx']); arrays={}
        for k in SURFACE & packed.keys():
            raw=base64.b64decode(packed[k],validate=True)
            if len(raw)!=shape[0]*shape[1]*2: raise ValueError(f'Wrong point field shape {k}')
            a=np.frombuffer(raw,dtype='<i2').reshape(shape)
            if not np.any(a!=grid['missing']):
                if k in CORE: raise ValueError(f'Empty point field {k}')
                continue
            scale=scales.get(k,grid['scale'])
            if k in self.meta['scales'] and self.meta['scales'][k]!=scale: raise ValueError('Point scale changed')
            self.meta['scales'][k]=scale; arrays[k]=a
        self.meta['frames'][str(hour)]=sorted(arrays)
        size=self.meta['tileSize']
        for y in range(0,shape[0],size):
            for x in range(0,shape[1],size):
                key=f'{x//size}-{y//size}'; self.keys.add(key)
                frame={k:base64.b64encode(v[y:y+size,x:x+size].tobytes()).decode('ascii') for k,v in arrays.items()}
                with open(Path(self.temp.name)/(key+'.jsonl'),'a') as stream:
                    stream.write(json.dumps([hour,frame],separators=(',',':'))+'\n')

    def finish(self):
        if set(self.meta['frames'])!={str(h) for h in self.meta['hours']}: raise ValueError('Incomplete point forecast')
        for key in sorted(self.keys):
            with open(Path(self.temp.name)/(key+'.jsonl')) as stream: frames=dict(json.loads(line) for line in stream)
            packet=dict(schema=3,run=self.meta['run'],generated=self.meta['generated'],key=key,frames=frames)
            with gzip.open(self.output/f'point-{key}.json.gz','wt',compresslevel=5) as stream: json.dump(packet,stream,separators=(',',':'))
        (self.output/'point-index.json').write_text(json.dumps(self.meta,separators=(',',':')))
        self.temp.cleanup()

