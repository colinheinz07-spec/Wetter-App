import base64
import gzip
import json
from pathlib import Path
import runpy
import tempfile
import numpy as np

PointTiles = runpy.run_path(str(Path(__file__).with_name('native-point.py')))
with tempfile.TemporaryDirectory() as root:
    grid=dict(west=7.,south=50.,step=.02,nx=10,ny=9,scale=.1,missing=-32768)
    writer=PointTiles['PointTiles'](root,'ICON-D2','run','generated',[0,1],size=8)
    raw=np.arange(90,dtype='<i2').reshape(9,10)
    for h in (0,1):
        packed={k:base64.b64encode((raw+h).tobytes()).decode() for k in PointTiles['CORE']}
        writer.add(grid,h,packed,{})
    writer.finish()
    m=json.loads(Path(root,'point-index.json').read_text())
    assert m['grid']==grid and m['hours']==[0,1]
    with gzip.open(Path(root,'point-1-1.json.gz'),'rt') as stream: packet=json.load(stream)
    assert packet['key']=='1-1'
    assert np.frombuffer(base64.b64decode(packet['frames']['1']['temp2']),dtype='<i2').tolist()==[89,90]
print('Native tile edge geometry and exact packed field values: OK')
