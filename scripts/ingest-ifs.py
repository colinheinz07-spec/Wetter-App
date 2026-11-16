"""Publish a reduced European IFS control forecast from ECMWF Open Data.

Use the official JSON-lines GRIB index and HTTP byte ranges. No third-party
forecast API or key is necessary. All fields belong to a single model run.
"""
import argparse
import concurrent.futures as futures
import datetime as dt
import json
import os
import runpy
import tempfile
import urllib.request
from pathlib import Path

import eccodes as ec
import numpy as np

ROOT = 'https://data.ecmwf.int/forecasts'
HOURS = list(range(0, 241, 6))
PRODUCTS = {'ifs': ('ifs', 'oper', 'fc', 'IFS'),
            'aifs': ('aifs-single', 'oper', 'fc', 'AIFS'),
            'aifs-ens-control': ('aifs-ens', 'enfo', 'cf', 'AIFS-ENS Control')}
PRODUCT = 'ifs'
GRID = dict(west=-25., south=34., step=.5, nx=135, ny=75, scale=.1, missing=-32768)
X = GRID['west'] + np.arange(GRID['nx'])*GRID['step']
Y = GRID['south'] + np.arange(GRID['ny'])*GRID['step']
pack = runpy.run_path(str(Path(__file__).with_name('ingest-icon.py')))['pack']
SURFACE = {'2t':('temp2',1,-273.15),'2d':('dew',1,-273.15),
           'msl':('slp',.01,0),'tcc':('cloud',100,0),'tp':('rainTotal',1000,0),
           '10u':('u10',1,0),'10v':('v10',1,0),'10fg':('gust',3.6,0),
           'lcc':('lowcloud',100,0),'mcc':('midcloud',100,0),'hcc':('highcloud',100,0),
           'tcwv':('pwat',1,0),'vis':('visibility',.001,0),'skt':('tground',1,-273.15),
           'mucape':('mucape',1,0),'ptype':('ptype',1,0),'cp':('convTotal',1000,0),
           'sf':('snowWaterTotal',1000,0),'sd':('snowWater',1000,0),'rsn':('snowDensity',1,0),
           'ssrd':('solarTotal',.001,0),'100u':('u100',1,0),'100v':('v100',1,0)}
SCALES={'mucape':1,'ptype':1,'solarTotal':10,'snowDensity':1}
CORE = {'temp2','dew','slp','cloud','rainTotal','u10','v10'}
LEVELS=(925,850,700,500,300,250,200)
PRESSURE = {('t',n):(f't{n}',1,-273.15) for n in LEVELS}
PRESSURE.update({('r',n):(f'rh{n}',1,0) for n in LEVELS})
PRESSURE.update({('gh',n):(f'z{n}',.1,0) for n in LEVELS})
PRESSURE.update({('z',n):(f'z{n}',1/98.0665,0) for n in LEVELS})
PRESSURE.update({(v,n):(f'{v}{n}',1,0) for v in ('u','v') for n in LEVELS})
PRESSURE.update({('q',n):(f'q{n}',1,0) for n in LEVELS})


def get(url, offset=None, length=None):
    headers = {'User-Agent':'WetterApp/1.0'}
    if offset is not None:
        headers['Range'] = f'bytes={offset}-{offset+length-1}'
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as res:
        if offset is not None and res.status != 206:
            raise ValueError('Expected HTTP partial content')
        data = res.read()
    if length is not None and len(data) != length:
        raise ValueError('Incomplete GRIB message')
    return data


def file_base(run, hour):
    stamp = run.strftime('%Y%m%d%H')
    model,stream,kind,_=PRODUCTS[PRODUCT]
    # Since IFS cycle 50r1 the short cycles also use stream=oper.
    return f'{ROOT}/{stamp[:8]}/{stamp[8:]}z/{model}/0p25/{stream}/{stamp}0000-{hour}h-{stream}-{kind}'


def index(run, hour):
    return [json.loads(line) for line in get(file_base(run,hour)+'.index').splitlines() if line.strip()]


def selected(rows):
    # Some ECMWF files carry both geopotential and geopotential height.
    # Prefer the direct height product to avoid duplicate downloads.
    heights={int(row['levelist']) for row in rows if row.get('levtype')=='pl' and row.get('param')=='gh'}
    for row in rows:
        param = row.get('param')
        if param=='z' and row.get('levtype')=='pl' and int(row.get('levelist',0)) in heights:continue
        specs = SURFACE.get(param) if row.get('levtype') == 'sfc' else PRESSURE.get((param,int(row.get('levelist',0)))) if row.get('levtype') == 'pl' else None
        if specs:
            yield row, specs


def choose_run(short=False,hours=HOURS):
    now = dt.datetime.now(dt.timezone.utc)
    base = now.replace(hour=now.hour//6*6,minute=0,second=0,microsecond=0)
    for i in range(6):
        run = base-dt.timedelta(hours=6*i)
        if PRODUCT=='ifs' and (run.hour in (6,18))!=short:continue
        try:
            rows = index(run,hours[-1]); keys={spec[0] for _,spec in selected(rows)}
            if CORE <= keys:
                return run
        except Exception as exc:
            print(f'{run}: {exc}',flush=True)
    raise RuntimeError(f'No complete recent {PRODUCT} cycle')


def sample(row, spec, run, hour):
    key, factor, shift = spec
    blob=get(file_base(run,hour)+'.grib2',int(row['_offset']),int(row['_length']))
    gid=ec.codes_new_from_message(blob)
    try:
        if ec.codes_get(gid,'gridType')!='regular_ll':
            raise ValueError('Unexpected grid')
        stamp=f"{ec.codes_get_long(gid,'dataDate'):08d}{ec.codes_get_long(gid,'dataTime')//100:02d}"
        if stamp!=run.strftime('%Y%m%d%H') or ec.codes_get_long(gid,'endStep')!=hour:
            raise ValueError('Mixed cycle or forecast step')
        if key in ('rainTotal','convTotal','snowWaterTotal','solarTotal') and ec.codes_get_long(gid,'startStep')!=0:
            raise ValueError('Expected accumulation since run start')
        ni,nj=ec.codes_get_long(gid,'Ni'),ec.codes_get_long(gid,'Nj')
        if ec.codes_get_long(gid,'alternativeRowScanning'):
            raise ValueError('Unsupported scan layout')
        values=ec.codes_get_values(gid)
        lat0=ec.codes_get_double(gid,'latitudeOfFirstGridPointInDegrees')
        lon0=ec.codes_get_double(gid,'longitudeOfFirstGridPointInDegrees')
        dx=ec.codes_get_double(gid,'iDirectionIncrementInDegrees')
        dy=ec.codes_get_double(gid,'jDirectionIncrementInDegrees')
        xi=np.rint(((X-lon0) if not ec.codes_get_long(gid,'iScansNegatively') else (lon0-X))%360/dx).astype(int)%ni
        yi=np.rint((Y-lat0)/dy*(1 if ec.codes_get_long(gid,'jScansPositively') else -1)).astype(int)
        if (yi<0).any() or (yi>=nj).any():raise ValueError('Grid coverage missing')
        grid=values.reshape(ni,nj).T if ec.codes_get_long(gid,'jPointsAreConsecutive') else values.reshape(nj,ni)
        out=grid[np.ix_(yi,xi)].astype(float)
        out[(out==ec.codes_get_double(gid,'missingValue'))|(~np.isfinite(out))|(np.abs(out)>1e8)]=np.nan
        # ECMWF AI products use WMO GRIB units for some fields, while IFS
        # local definitions use fractions and metres. Read actual GRIB units.
        units=ec.codes_get(gid,'units')
        if key in ('cloud','lowcloud','midcloud','highcloud'):
            if units in ('%','percent'):factor=1
            elif units in ('(0 - 1)','1','Numeric'):factor=100
            else:raise ValueError(f'Unexpected cloud units: {units}')
        if key in ('rainTotal','convTotal','snowWaterTotal','snowWater'):
            if units in ('kg m**-2','kg m-2','mm'):factor=1
            elif units in ('m','m of water equivalent'):factor=1000
            else:raise ValueError(f'Unexpected water units: {units}')
        return key,out*factor+shift
    finally:
        ec.codes_release(gid)


def frame(run,hour):
    entries=list(selected(index(run,hour)))
    def read(entry):
        try:return sample(*entry,run,hour)
        except Exception as exc:
            print(f'+{hour} {entry[1][0]}: {exc}',flush=True)
            return None
    with futures.ThreadPoolExecutor(max_workers=4) as pool:
        values=dict(r for r in pool.map(read,entries) if r is not None)
    if hour==0 and 'rainTotal' not in values and 'temp2' in values:
        values['rainTotal']=np.where(np.isfinite(values['temp2']),0,np.nan)
    if not CORE <= values.keys() or not all(np.isfinite(values[k]).any() for k in CORE):
        raise ValueError(f'Missing core IFS fields at +{hour}: {CORE-values.keys()}')
    for key in ('cloud','lowcloud','midcloud','highcloud'):
        if key in values:
            values[key]=np.where((values[key]>=-.1)&(values[key]<=100.1),np.clip(values[key],0,100),np.nan)
    if not np.isfinite(values['cloud']).any():raise ValueError('Invalid cloud cover units')
    u,v=values.pop('u10'),values.pop('v10')
    values['wind']=np.hypot(u,v)*3.6
    values['winddir']=(np.degrees(np.arctan2(-u,-v))+360)%360
    t,d=values['temp2'],values['dew']
    values['rh2']=np.clip(100*np.exp(17.625*d/(243.04+d)-17.625*t/(243.04+t)),0,100)
    # AIFS publishes specific humidity rather than relative humidity on pressure levels.
    for level in LEVELS:
        q=values.pop(f'q{level}',None); temp=values.get(f't{level}')
        if q is not None and temp is not None and f'rh{level}' not in values:
            e=q*level/(.622+.378*q)
            es=6.112*np.exp(17.67*temp/(temp+243.5))
            values[f'rh{level}']=np.clip(100*e/es,0,100)
    if 'u300' in values and 'v300' in values:values['jet']=np.hypot(values['u300'],values['v300'])
    if 'u100' in values and 'v100' in values:values['wind100']=np.hypot(values.pop('u100'),values.pop('v100'))*3.6
    if 'snowWater' in values and 'snowDensity' in values:
        water,density=values['snowWater'],values['snowDensity']
        values['snowdepth']=np.divide(water*100,density,out=np.full_like(t,np.nan),where=density>0)
        values['snowdepth'][water==0]=0
    for low,key in [(850,'lapse'),(700,'lapse7')]:
        if all(k in values for k in (f't{low}','t500',f'z{low}','z500')):
            thickness=(values['z500']-values[f'z{low}'])/100
            values[key]=np.divide(values[f't{low}']-values['t500'],thickness,out=np.full_like(t,np.nan),where=thickness>0)
    print(f'{PRODUCT} +{hour}h: {len(values)} fields',flush=True)
    return str(hour),{key:pack(val,SCALES.get(key,.1)) for key,val in values.items()}


def main():
    global PRODUCT
    parser=argparse.ArgumentParser();parser.add_argument('--short',action='store_true');parser.add_argument('--product',choices=PRODUCTS,default='ifs');args=parser.parse_args()
    PRODUCT=args.product
    if args.short and PRODUCT!='ifs':parser.error('--short only applies to IFS')
    hours=list(range(0,91,6)) if args.short else list(range(0,361,6)) if PRODUCT!='ifs' else HOURS
    run=choose_run(args.short,hours)
    out=Path('data/ifs-short.json' if args.short else f'data/{PRODUCT}.json');out.parent.mkdir(exist_ok=True)
    if out.exists():
        previous=json.loads(out.read_text())
        if dt.datetime.fromisoformat(previous['run'])>=run and 't925' in previous['frames'].get('0',{}):
            print('IFS cycle already published');return
    with futures.ThreadPoolExecutor(max_workers=2) as pool:
        frames=dict(pool.map(lambda hour:frame(run,hour),hours))
    name=PRODUCTS[PRODUCT][3]
    payload=dict(schema=1,model=name,source=f'ECMWF {name} Open Data (CC BY 4.0), adapted',sourceUrl=ROOT+'/',run=run.isoformat(),generated=dt.datetime.now(dt.timezone.utc).isoformat(),grid=GRID,scales=SCALES,hours=hours,frames=frames)
    with tempfile.NamedTemporaryFile('w',dir=out.parent,delete=False) as target:
        json.dump(payload,target,separators=(',',':'));name=target.name
    os.replace(name,out)


if __name__=='__main__':main()
