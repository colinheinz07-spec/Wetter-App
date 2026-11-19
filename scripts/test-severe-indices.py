"""Deterministic warm-season/stable/missing-profile and publication tests."""
import base64
import datetime as dt
import gzip
import json
import runpy
import tempfile
from pathlib import Path
import numpy as np

HERE=Path(__file__).parent
api=runpy.run_path(str(HERE/'severe-indices.py'));levels=api['LEVELS']
vals={k:np.array(v,float) for k,v in dict(ps=[1010]*4,orog=[0]*4,temp2=[30,10,30,30],dew=[23,-2,23,23],wind=[18]*4,winddir=[180]*4).items()}
for p in levels:
    z=8000*np.log(1010/p);warm=max(-62,30-7.8*z/1000) if p>200 else -57+(200-p)/40;stable=max(-55,10-4*z/1000)
    for k,v in [('z',[z/10]*4),('t',[warm,stable,warm,warm]),('rh',[75 if p>=850 else 45,45,75 if p>=850 else 45,75 if p>=850 else 45]),('u',[5+z/1000*3]*4),('v',[5-z/1000*.5]*4)]:vals[k+str(p)]=np.array(v,float)
vals['rh700'][2]=np.nan
vals['ps'][3]=np.nan
with np.errstate(all='ignore'):
    out=api['derive_chunk'](vals,levels)
    for key in ('scp','stp','ship','downburst','dcape'):
        assert np.isfinite(out[key][0]) and out[key][0]>0,(key,out[key])
        assert np.isnan(out[key][2:]).all(),(key,out[key])
    for key in ('scp','stp','ship','downburst','cape','mucape','mlcape'):assert out[key][1]==0,(key,out[key])
    assert np.isnan(out['cin'][1]),'No LFC means no CIN-to-LFC value'
    assert 500<out['dcape'][0]<1600
    assert out['dcape'][0]>out['dcape'][1]
    assert np.isclose(out['dcapeSpeed'][0],3.6*np.sqrt(2*out['dcape'][0]))
    assert np.isclose(out['ehi03'][0],out['mlcape'][0]*out['srh03'][0]/160000)
    # Saturated theta-e inversion preserves temperature (<0.03 K rounding error).
    pp=np.array([1000.,850.,500.]);tt=np.array([25.,8.,-20.]);te=api['thetae'](pp,tt,api['vapor'](tt))
    np.testing.assert_allclose(api['moist'](pp,te),tt,atol=.03)

grid=dict(west=8.,south=50.,step=.02,nx=2,ny=2,missing=-32768,scale=.1)
def pack(a,scale):return base64.b64encode(np.where(np.isfinite(a),np.rint(a/scale),-32768).astype('<i2').tobytes()).decode()
scales={'orog':1,'mlcape':1};frame={k:pack(a,scales.get(k,.1)) for k,a in vals.items()}
frame.update(slp=pack(np.full(4,1010.),.1),cloud=pack(np.full(4,50.),.1),rainTotal=pack(np.zeros(4),.1),mlcape=pack(np.full(4,1000.),1))
result,newscales=api['add_diagnostics'](grid,frame,scales,chunk=2)
assert result['mlcape']==frame['mlcape'],'Original model parameter was overwritten'
assert 'hail' not in result,'Hail diameter must not be inferred from CAPE or SHIP'
assert newscales['scp']==.01
for key in ('scp','stp','ship','dcape','downburst'):
    a=np.frombuffer(base64.b64decode(result[key]),'<i2');assert a[0]>0 and a[2]==-32768 and a[3]==-32768,(key,a)
assert api['add_diagnostics'](grid,{'temp2':frame['temp2']},{})[0]=={'temp2':frame['temp2']}

Maps=runpy.run_path(str(HERE/'ingest-native-maps.py'))['Maps']
with tempfile.TemporaryDirectory() as d:
    writer=Maps(d,'ICON-D2','2026-07-01T12:00:00+00:00',[0,1]);writer.add(grid,0,frame,scales);writer.add(grid,1,frame,scales);writer.finish()
    m=json.loads((Path(d)/'index.json').read_text());p=json.loads((Path(d)/'point-index.json').read_text())
    for k in ('scp','stp','ship','dcape','downburst'):
        assert k in m['frames']['0'] and k in p['frames']['0'] and k in m['derivedFields']['0'] and k in p['derivedFields']['0']
        with gzip.open(Path(d)/f'0-{k}.json.gz','rt') as f:assert json.load(f)['field']==k
    assert 'mlcape' not in m['derivedFields']['0']

ruc=runpy.run_path(str(HERE/'ingest-ruc-hail.py'))
now=dt.datetime(2026,7,1,14,30,tzinfo=dt.timezone.utc);listing=' '.join(ruc['filename'](h) for h in ruc['HOURS'])
assert ruc['choose_run'](now,source=lambda _:['2026-07-01T14:00','2026-07-01T13:00'],download=lambda url: (listing if '13%3A00' in url else 'PT000H00M.grib2').encode())=='2026-07-01T13:00'
v=ruc['hail_cm'](np.array([.035,0.,np.nan,.1]),np.array([0,1,2,3]),np.array([True,True,True,False]))
assert np.isclose(v[0],3.5) and v[1]==0 and np.isnan(v[2:]).all()
with tempfile.TemporaryDirectory() as d:
    Points=runpy.run_path(str(HERE/'native-point.py'))['PointTiles'];p=Points(d,'ICON-D2-RUC','2026-07-01T13:00:00+00:00','2026-07-01T14:00:00+00:00',[0,1],required={'hail'})
    for h in [0,1]:p.add(grid,h,{'hail':pack(v,.1)},{'hail':.1})
    p.finish();assert json.loads((Path(d)/'point-index.json').read_text())['frames']['0']==['hail']
print('Warm/stable/missing profiles, moist thermodynamics, verified equations, native map and point packets, and RUC selection/units: PASS')
