"""Bound duplicated point profiles while preserving every original map field."""
import ast
import base64
import gzip
import json
import runpy
import tempfile
from pathlib import Path

import numpy as np

root=Path(__file__).parent
PointTiles=runpy.run_path(str(root/'native-point.py'))['PointTiles']
check_size=runpy.run_path(str(root/'check-native-snapshot-size.py'))['check_size']
grid=dict(west=7.,south=50.,step=.02,nx=8,ny=8,scale=.1,missing=-32768)
pack=lambda value:base64.b64encode(np.full((8,8),value,dtype='<i2').tobytes()).decode()
core={'temp2','dew','wind','slp','cloud','rainTotal'}
with tempfile.TemporaryDirectory() as folder:
    writer=PointTiles(folder,'ICON-EU','run','generated',[0,36,42],size=8,profile_horizon=36)
    fields=core|{'t850','rh700','u500','z925','u100','v100','ww','cloudbase','mlcape','snowGspTotal'}
    for hour in (0,36,42):writer.add(grid,hour,{k:pack(hour+10) for k in fields},{})
    writer.finish()
    meta=json.loads(Path(folder,'point-index.json').read_text())
    with gzip.open(Path(folder,'point-0-0.json.gz'),'rt') as f:packet=json.load(f)
    assert meta['profileHorizonHours']==36
    for hour in ('0','36'):assert 't850' in packet['frames'][hour]
    assert 't850' not in packet['frames']['42'] and 'u500' not in packet['frames']['42']
    assert core|{'u100','v100','ww','cloudbase','mlcape','snowGspTotal'}<=packet['frames']['42'].keys()
    assert meta['frames']['42']==sorted(packet['frames']['42'])
    Path(folder,'42-t850.json.gz').write_bytes(b'original map field remains')
    (Path(folder)/'.git').mkdir()
    (Path(folder)/'.git/objects').write_bytes(b'ignored git metadata'*1000)
    expected=sum(p.stat().st_size for p in Path(folder).glob('*.json*'))
    assert check_size(folder,expected+1)==expected
    try:check_size(folder,expected)
    except ValueError:pass
    else:raise AssertionError('Publication budget was ignored')

# DWD publishes HBAS_CON and HTOP_CON; the previous BAS_CON/TOP_CON URLs were 404.
tree=ast.parse((root/'ingest-icon.py').read_text())
extra=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='EXTRA' for t in n.targets))
assert extra['hbas_con']==('cloudbase',1,0,1)
assert extra['htop_con']==('cloudtop',1,0,1)
assert 'bas_con' not in extra and 'top_con' not in extra
print('PASS: current point profiles, long-range surface values, retained original map fields, payload budget and DWD cloud-height aliases')
