"""Offline tests for regional native map cadence and sparse fields."""
import base64
import json
from pathlib import Path
import runpy
import sys
import tempfile
import types
import numpy as np

api=runpy.run_path(str(Path(__file__).with_name('ingest-native-maps.py')))
hours=api['germany_hours']
assert hours('icon-d2')==list(range(49))
assert hours('icon-eu')[78:81]==[78,81,84]
assert hours('gfs')[120:123]==[120,123,126] and hours('gfs')[-1]==384
assert hours('ifs')[48:51]==[144,150,156] and hours('ifs')[-1]==360
assert hours('ifs-short')[-1]==90 and hours('ifs-short')[1]==3
assert hours('aifs')[1]==6
# The accumulation math has no GRIB dependency. Stub ecCodes for this offline unit test.
sys.modules.setdefault('eccodes',types.ModuleType('eccodes'))
cum=runpy.run_path(str(Path(__file__).with_name('ingest-gfs.py')))['cumulative_at']
history={0:np.array([0.]),1:np.array([2.]),2:np.array([5.]),120:np.array([20.])}
assert cum(123,{120:np.array([6.])},history)[0]==26
assert cum(2,{0:np.array([5.])},{0:history[0],1:history[1]})[0]==5
assert cum(2,{1:np.array([3.])},{0:history[0],1:history[1]})[0]==5
assert cum(2,{1:np.array([3.])},{0:history[0]}) is None
with tempfile.TemporaryDirectory() as output:
    grid=dict(west=4.,south=47.,step=.25,nx=2,ny=2,scale=.1,missing=-32768)
    raw=base64.b64encode(np.arange(4,dtype='<i2').tobytes()).decode()
    writer=api['Maps'](output,'ICON-EU','2026-11-17T12:00:00Z',[0,1,3],points=False,core_hours=[0,3])
    writer.add(grid,0,{k:raw for k in api['CORE']},{})
    writer.add(grid,1,{'wind':raw},{})
    writer.add(grid,3,{k:raw for k in api['CORE']},{})
    writer.finish()
    meta=json.loads(Path(output,'index.json').read_text())
    assert meta['hours']==[0,1,3] and meta['coreHours']==[0,3]
    assert meta['frames']['1']==['wind'] and not Path(output,'point-index.json').exists()
print('Exact model cadences, sparse fields and map-only publication: OK')
