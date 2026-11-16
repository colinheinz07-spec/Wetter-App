"""Synthetic original-grid publication test; no network needed."""
import base64
import gzip
import json
import runpy
import tempfile
from pathlib import Path
import numpy as np

here=Path(__file__).parent
n=runpy.run_path(str(here/'native-temperature.py'))
pack=runpy.run_path(str(here/'ingest-icon.py'))['pack']
x=np.array([7.8,7.82,7.84]);y=np.array([50.5,50.52])
g=n['grid_for'](x,y);v=np.array([[3.,6.,9.],[1.,np.nan,-1.]])
tiles={};n['add_frame'](tiles,g,0,'temp2',v,pack)
with tempfile.TemporaryDirectory() as root:
    n['publish'](root,'ICON-D2','2026-11-16T18:00:00+00:00',[0],g,tiles,{0:pack(v,.1)})
    root=Path(root)
    m=json.loads((root/'index.json').read_text())
    with gzip.open(root/'map-0.json.gz','rt') as f:frame=json.load(f)
    with gzip.open(root/'0-0.json.gz','rt') as f:tile=json.load(f)
    assert m['grid']['nx']==3 and m['mapHours']==[0]
    assert frame['temp2']==tile['frames']['0']['temp2']
    assert list(np.frombuffer(base64.b64decode(frame['temp2']),dtype='<i2'))==[30,60,90,10,-32768,-10]
print('Original coordinates, map and point packet values agree')

# Yesterday's 21Z appears in the same directory as the unfinished new 21Z.
# The latest complete cycle is today's 18Z, not yesterday's 21Z.
import datetime as dt
api=runpy.run_path(str(here/'ingest-icon.py'))
def offers(model,cycle,var):
    stamps={'21':['2026111521'],'18':['2026111618']} .get(cycle,[])
    return {(s,h):'fixture' for s in stamps for h in (0,1)}
assert api['choose_run']('icon-d2',[0,1],now=dt.datetime(2026,11,16,21,15,tzinfo=dt.timezone.utc),source=offers)[0]=='2026111618'
print('Cycle selection uses the full UTC date, not directory hour')
