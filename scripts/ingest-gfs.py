"""NOAA GFS 0.25° operational forecast, regional GRIB2 subsets via NOMADS.

Output uses the same verified grid contract as ICON/IFS. The regional product
is sampled at 0.5° and 6 h, not represented as native resolution.
"""
import datetime as dt
import json
import os
import runpy
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import eccodes as ec
import numpy as np

ROOT = 'https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl'
BUCKET = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'
HOURS = list(range(0, 241, 6))
GRID = dict(west=-25., south=34., step=.5, nx=135, ny=75, scale=.1, missing=-32768)
NATIVE_STEP = None
X = GRID['west'] + np.arange(GRID['nx'])*GRID['step']
Y = GRID['south'] + np.arange(GRID['ny'])*GRID['step']
pack = runpy.run_path(str(Path(__file__).with_name('ingest-icon.py')))['pack']
# GRIB discipline/category/number, and first fixed surface type/level.
SPECS = {}
def field(cat, num, surface, level, key, factor=1, offset=0, scale=.1):
    SPECS[(0,cat,num,surface,level)] = (key,factor,offset,scale)
for n,s,k in [(0,2,'temp2'),(6,2,'dew'),(0,0,'tground')]:
    field(0,n,103 if s else 1,s,k,1,-273.15)
field(1,1,103,2,'rh2')
field(2,2,103,10,'u10');field(2,3,103,10,'v10')
field(2,2,103,100,'u100');field(2,3,103,100,'v100')
field(2,22,1,0,'gust',3.6)
field(3,1,101,0,'slp',.01)
field(3,0,1,0,'ps',.01)
field(3,5,1,0,'orog',scale=1)
field(6,1,200,0,'cloud');field(6,1,10,0,'cloud')
field(6,1,214,0,'lowcloud');field(6,1,224,0,'midcloud');field(6,1,234,0,'highcloud')
field(1,8,1,0,'rainInterval');field(1,10,1,0,'convInterval')
field(1,3,200,0,'pwat');field(1,3,10,0,'pwat')
field(1,11,1,0,'snowdepth',100);field(1,13,1,0,'snowWater')
field(19,0,1,0,'visibility',.001)
field(7,6,1,0,'cape',scale=1);field(7,7,1,0,'cin',scale=1)
field(7,6,108,0,'mlcape',scale=1);field(7,7,108,0,'mlcin',scale=1)
field(7,10,1,0,'li');field(3,5,4,0,'freezing',scale=1)
field(16,196,10,0,'reflectivity');field(16,196,200,0,'reflectivity')
field(2,2,100,30000,'u300');field(2,3,100,30000,'v300')
for lev in (1000,975,950,925,900,850,800,700,600,500,400,300,250,200,150,100):
    for cat,num,key,factor,offset in [(0,0,'t',1,-273.15),(1,1,'rh',1,0),(3,5,'z',.1,0),(2,2,'u',1,0),(2,3,'v',1,0)]:
        field(cat,num,100,lev*100,f'{key}{lev}',factor,offset)

VARS = 'TMP DPT RH UGRD VGRD PRMSL PRES TCDC LCDC MCDC HCDC APCP ACPCP PWAT SNOD WEASD VIS CAPE CIN LFTX HGT GUST REFC CRAIN CSNOW CFRZR CICEP'.split()
LEVELS = ['surface','2_m_above_ground','10_m_above_ground','100_m_above_ground','mean_sea_level','entire_atmosphere','entire_atmosphere_(considered_as_a_single_layer)','low_cloud_layer','middle_cloud_layer','high_cloud_layer','0C_isotherm','180-0_mb_above_ground']+[f'{x}_mb' for x in (925,850,700,500,300,250,200)]
CORE = {'temp2','dew','slp','cloud','u10','v10','rainInterval'}
SCALES = {spec[0]:spec[3] for spec in SPECS.values() if spec[3]!=.1}
SCALES.update(ptype=1)

def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'WetterApp/1.0 (regional forecast; NOAA NOMADS)'})
    with urllib.request.urlopen(req,timeout=90) as response:return response.read()

def filename(run,h):return f'gfs.t{run:%H}z.pgrb2.0p25.f{h:03d}'

def choose_run(hours=HOURS):
    now=dt.datetime.now(dt.timezone.utc);base=now.replace(hour=now.hour//6*6,minute=0,second=0,microsecond=0)
    for i in range(8):
        run=base-dt.timedelta(hours=6*i)
        try:
            url=f'{BUCKET}/gfs.{run:%Y%m%d}/{run:%H}/atmos/{filename(run,hours[-1])}.idx'
            if b':TMP:2 m above ground:' in get(url):return run
        except Exception as e:print(f'{run}: {e}',flush=True)
    raise RuntimeError('No complete GFS run')

def subset(run,h):
    params=dict(file=filename(run,h),dir=f'/gfs.{run:%Y%m%d}/{run:%H}/atmos',subregion='',leftlon=float(X[0]),rightlon=float(X[-1]),toplat=float(Y[-1]),bottomlat=float(Y[0]))
    levels=LEVELS+([f'{x}_mb' for x in (1000,975,950,900,800,600,400,150,100)] if NATIVE_STEP is not None else [])
    params.update({f'var_{v}':'on' for v in VARS});params.update({f'lev_{v}':'on' for v in levels})
    endpoint=ROOT.replace('filter_gfs_0p25.pl','filter_gfs_0p25_1hr.pl') if h%3 else ROOT
    url=endpoint+'?'+urllib.parse.urlencode(params)
    # NOMADS requests are intentionally serial and spaced out.
    for attempt in range(3):
        time.sleep(10)
        try:
            blob=get(url)
            if not blob.startswith(b'GRIB'):raise ValueError('No GRIB subset')
            return blob
        except Exception as e:
            print(f'GFS +{h}: {e}',flush=True)
            if attempt==2:raise

def sample(gid):
    if ec.codes_get(gid,'gridType')!='regular_ll' or ec.codes_get_long(gid,'alternativeRowScanning'):raise ValueError('Unexpected GRIB grid')
    ni,nj=ec.codes_get_long(gid,'Ni'),ec.codes_get_long(gid,'Nj')
    lat0=ec.codes_get_double(gid,'latitudeOfFirstGridPointInDegrees');lon0=ec.codes_get_double(gid,'longitudeOfFirstGridPointInDegrees')
    dx=ec.codes_get_double(gid,'iDirectionIncrementInDegrees');dy=ec.codes_get_double(gid,'jDirectionIncrementInDegrees')
    xi=np.rint((((lon0-X) if ec.codes_get_long(gid,'iScansNegatively') else (X-lon0))%360)/dx).astype(int)
    yi=np.rint((Y-lat0)/dy*(1 if ec.codes_get_long(gid,'jScansPositively') else -1)).astype(int)
    if NATIVE_STEP is not None:
        if not np.isclose(dx,NATIVE_STEP,rtol=0,atol=1e-6) or not np.isclose(dy,NATIVE_STEP,rtol=0,atol=1e-6):raise ValueError('Unexpected native GFS spacing')
        xx=(lon0+(-1 if ec.codes_get_long(gid,'iScansNegatively') else 1)*xi*dx+180)%360-180
        yy=lat0+(1 if ec.codes_get_long(gid,'jScansPositively') else -1)*yi*dy
        if not np.allclose(xx,X,atol=1e-6,rtol=0) or not np.allclose(yy,Y,atol=1e-6,rtol=0):raise ValueError('GFS native grid not aligned')
    if (xi>=ni).any() or (yi<0).any() or (yi>=nj).any():raise ValueError(f'Subset coverage mismatch {ni}x{nj}, {lon0}, {lat0}')
    v=ec.codes_get_values(gid);v=v.reshape(ni,nj).T if ec.codes_get_long(gid,'jPointsAreConsecutive') else v.reshape(nj,ni)
    v=v[np.ix_(yi,xi)].astype(float);v[(v==ec.codes_get_double(gid,'missingValue'))|(~np.isfinite(v))|(np.abs(v)>1e8)]=np.nan
    return v

def cumulative_at(hour,windows,history):
    # GRIB accumulation windows may reset every 6h or span a single hour.
    # Recover totals only from a known accumulation anchor, never interpolate.
    for start in sorted(windows,reverse=True):
        if start not in history:continue
        total=history[start]+windows[start]
        prior=history[max(history)]
        return np.where(total>=prior-.15,np.maximum(total,prior),np.nan)
    return None

def frame(run,h,previous):
    fields={};types={};accum={}
    with tempfile.TemporaryFile() as f:
        f.write(subset(run,h));f.seek(0)
        while True:
            g=ec.codes_grib_new_from_file(f)
            if g is None:break
            try:
                stamp=f"{ec.codes_get_long(g,'dataDate'):08d}{ec.codes_get_long(g,'dataTime')//100:02d}"
                if stamp!=run.strftime('%Y%m%d%H') or ec.codes_get_long(g,'endStep')!=h:raise ValueError('Wrong GFS run or step')
                cat,num,typ=map(lambda k:ec.codes_get_long(g,k),('parameterCategory','parameterNumber','typeOfFirstFixedSurface'))
                lev=ec.codes_get_long(g,'scaledValueOfFirstFixedSurface') if typ in (100,103,108) else 0
                spec=SPECS.get((ec.codes_get_long(g,'discipline'),cat,num,typ,lev))
                short=ec.codes_get(g,'shortName');name=ec.codes_get(g,'name').lower()
                # NCEP local parameters and cloud-layer conventions differ from WMO.
                if 'categorical' in name and typ==1:
                    for label,code in [('freezing rain',3),('ice pellets',8),('snow',5),('rain',1)]:
                        if label in name:types[code]=sample(g);break
                    continue
                if 'composite reflectivity' in name:spec=('reflectivity',1,0,.1)
                if 'low cloud cover' in name:spec=('lowcloud',1,0,.1)
                if 'medium cloud cover' in name:spec=('midcloud',1,0,.1)
                if 'high cloud cover' in name:spec=('highcloud',1,0,.1)
                if not spec:continue
                key,factor,offset,_=spec
                if key in ('rainInterval','convInterval'):
                    start=ec.codes_get_long(g,'startStep')
                    if 0<=start<h:accum.setdefault(key,{})[start]=sample(g)*factor+offset
                    continue
                if key in fields:continue
                fields[key]=sample(g)*factor+offset
            finally:ec.codes_release(g)
    if h==0:
        fields['rainInterval']=np.where(np.isfinite(fields['temp2']),0,np.nan)
        fields['convInterval']=fields['rainInterval'].copy()
    else:
        for key,options in accum.items():
            history=previous.get(key,{})
            if history:
                total=cumulative_at(h,options,history)
                if total is not None:fields[key]=total
    if not CORE<=fields.keys():raise RuntimeError(f'GFS +{h} missing {CORE-fields.keys()}, obtained {sorted(fields)}')
    for key,total in [('rainInterval','rainTotal'),('convInterval','convTotal')]:
        if key in fields:
            value=fields.pop(key);previous.setdefault(key,{})[h]=value;fields[total]=value
    u,v=fields.pop('u10'),fields.pop('v10');fields['wind']=np.hypot(u,v)*3.6;fields['winddir']=(np.degrees(np.arctan2(-u,-v))+360)%360
    if 'u100' in fields and 'v100' in fields:fields['wind100']=np.hypot(fields.pop('u100'),fields.pop('v100'))*3.6
    if 'u300' in fields and 'v300' in fields:fields['jet']=np.hypot(fields['u300'],fields['v300'])
    if types:
        p=np.zeros_like(fields['temp2']);valid=np.zeros_like(p,dtype=bool)
        for code in (1,5,8,3):
            if code in types:valid|=np.isfinite(types[code]);p[types[code]>.5]=code
        if 1 in types and 5 in types:p[(types[1]>.5)&(types[5]>.5)&(p==5)]=7
        fields['ptype']=np.where(valid,p,np.nan)
    for low,key in [(850,'lapse'),(700,'lapse7')]:
        if all(k in fields for k in (f't{low}','t500',f'z{low}','z500')):
            thickness=(fields['z500']-fields[f'z{low}'])/100;fields[key]=np.divide(fields[f't{low}']-fields['t500'],thickness,out=np.full_like(thickness,np.nan),where=thickness>0)
    print(f'GFS +{h:03d}h: {len(fields)} fields',flush=True)
    return {key:pack(val,SCALES.get(key,.1)) for key,val in fields.items()}

def main():
    run=choose_run();out=Path('data/gfs.json');out.parent.mkdir(exist_ok=True)
    if out.exists() and dt.datetime.fromisoformat(json.loads(out.read_text())['run'])>=run:
        print('GFS already published');return
    previous={};frames={str(h):frame(run,h,previous) for h in HOURS}
    payload=dict(schema=1,model='GFS',source='NOAA/NCEP GFS Open Data, adapted',sourceUrl=ROOT,run=run.isoformat(),generated=dt.datetime.now(dt.timezone.utc).isoformat(),grid=GRID,scales=SCALES,hours=HOURS,frames=frames)
    temp=out.with_suffix('.tmp');temp.write_text(json.dumps(payload,separators=(',',':')))
    if temp.stat().st_size>90_000_000:raise ValueError('GFS snapshot exceeds publication limit')
    os.replace(temp,out)

if __name__=='__main__':main()

