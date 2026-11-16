"""Publish compact native hourly ICON surface forecasts, independently of maps.

Keep the earlier UTC-day run as a short prefix for already elapsed periods.
Never interpolate precipitation or mix cumulative fields from different runs.
"""
import argparse
import concurrent.futures
import datetime as dt
import gzip
import json
import runpy
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

api=runpy.run_path(str(Path(__file__).with_name('ingest-icon.py')))
BASE=api['VARIABLES']
EXTRA={'ww':('ww',1,0,1),'vmax_10m':('gust',3.6,0,.1),'h_snow':('snowdepth',100,0,.1),'relhum_2m':('rh2',1,0,.1),'vis':('visibility',.001,0,.1),'tmin_2m':('tmin',1,-273.15,.1),'tmax_2m':('tmax',1,-273.15,.1)}
CORE=('temp2','dew','wind','winddir','slp','rainTotal','cloud')
NOW=dt.datetime.now(dt.timezone.utc)
DAY=NOW.astimezone(ZoneInfo('Europe/Berlin')).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(dt.timezone.utc)

def timestamp(s):return dt.datetime.fromisoformat(s)

def listing(model,stamp,variables):
    def load(v):
        try:return v,api['listing'](model,stamp[-2:],v)
        except Exception as exc:
            print(f'{model} {v}: {exc}',flush=True);return v,{}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:return dict(pool.map(load,variables))

def build(model,stamp,hours,offers,existing):
    cfg=api['MODELS'][model];x,y=api['target_grid'](cfg)
    grid=dict(west=float(x[0]),south=float(y[0]),step=cfg['delta'],nx=len(x),ny=len(y),scale=.1,missing=-32768)
    run=dt.datetime.strptime(stamp,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc)
    candidates=[d for d in existing if timestamp(d['run'])==run and d['grid']==grid]
    extra=listing(model,stamp,EXTRA)
    def read(v,h):return api['sample_grib'](api['download'](offers[v][stamp,h]),x,y,stamp,h)
    def frame(h):
        reuse=next((d for d in candidates if str(h) in d['frames'] and all(k in d['frames'][str(h)] for k in CORE)),None)
        if reuse:
            field=reuse['frames'][str(h)]
            result={k:field[k] for k in (*CORE,*(v[0] for v in EXTRA.values())) if k in field and (k not in ('tmin','tmax') or reuse.get('extremaWindowHours')==6)}
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                vals=dict(zip(BASE,pool.map(lambda v:None if v=='tot_prec' and h==0 else read(v,h),BASE)))
            t=vals['t_2m']-273.15;u,v=vals['u_10m'],vals['v_10m'];rain=vals['tot_prec']
            if not np.isfinite(t).any():raise ValueError('Empty temperature grid')
            if rain is None:rain=np.where(np.isfinite(t),0,np.nan)
            result={k:api['pack'](a,.1) for k,a in [('temp2',t),('dew',vals['td_2m']-273.15),('wind',np.hypot(u,v)*3.6),('winddir',(np.degrees(np.arctan2(-u,-v))+360)%360),('slp',vals['pmsl']/100),('rainTotal',rain),('cloud',vals['clct'])]}
        def optional(v):
            k,factor,offset,scale=EXTRA[v];url=extra[v].get((stamp,h))
            if k in ('tmin','tmax') and h==0:return None
            if k in result or not url:return None
            interval=((h-1)//6*6,'min' if k=='tmin' else 'max') if k in ('tmin','tmax') else None
            try:return k,api['pack'](api['sample_grib'](api['download'](url),x,y,stamp,h,interval)*factor+offset,scale)
            except Exception as exc:print(f'{model} +{h} {v}: {exc}',flush=True);return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:result.update(r for r in pool.map(optional,EXTRA) if r)
        print(f'{model} hourly {stamp} +{h:02d}',flush=True)
        return str(h),result
    # Four simultaneous GRIB transfers, bounded memory.
    frames=dict(frame(h) for h in hours)
    return dict(schema=1,model=cfg['name'],source='DWD Open Data · stündliche Vorhersage',run=run.isoformat(),generated=NOW.isoformat(),grid=grid,scales={k:s for k,_,_,s in EXTRA.values()},extremaWindowHours=6,hours=hours,frames=frames)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',choices=('icon-d2','icon-eu'));args=parser.parse_args()
    for model in ([args.model] if args.model else ('icon-d2','icon-eu')):
        path=Path(f'data/{model}-hourly.json.gz');previous=[]
        if path.exists():
            with gzip.open(path,'rt') as f:previous=json.load(f)['runs']
        base=json.loads(Path(f'data/{model}.json').read_text());existing=previous+[base]
        try:
            # Short ICON-D2 cycles still provide enough native hourly data
            # for the next night. Do not wait for a 48-hour main cycle.
            stamp,offers=api['choose_run'](model,list(range(28)))
            last=27
            while last<48 and all((stamp,last+1) in offers[v] for v in BASE):last+=1
            hours=list(range(last+1))
            run=dt.datetime.strptime(stamp,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc)
            latest=next((d for d in previous if timestamp(d['run'])==run and d['hours']==hours and d.get('extremaWindowHours')==6),None)
            if latest is None:latest=build(model,stamp,hours,offers,existing)
            runs=[latest]
            # Keep sufficient previous hourly history for the current UTC day.
            if run>DAY:
                cutoff=run
                anchors=[d for d in previous if timestamp(d['run'])<=DAY and timestamp(d['run'])+dt.timedelta(hours=d['hours'][-1])>=cutoff]
                if anchors:
                    anchor=max(anchors,key=lambda d:timestamp(d['run']))
                    last=int((cutoff-timestamp(anchor['run'])).total_seconds()/3600)
                    # Retain coverage through the first block following the update.
                    last=min(anchor['hours'][-1],last+6)
                    runs.append({**anchor,'hours':list(range(last+1)),'frames':{str(h):anchor['frames'][str(h)] for h in range(last+1)}})
                else:
                    # Local midnight is not necessarily a model-cycle hour.
                    anchor_run=DAY.replace(hour=DAY.hour//6*6)
                    anchor_stamp=anchor_run.strftime('%Y%m%d%H');last=int((cutoff-anchor_run).total_seconds()/3600)+6
                    if last>0:
                        try:
                            anchor_offers=listing(model,anchor_stamp,BASE)
                            runs.append(build(model,anchor_stamp,list(range(last+1)),anchor_offers,existing))
                        except Exception as exc:print(f'{model} midnight backfill unavailable: {exc}',flush=True)
            if runs==previous:continue
            temp=path.with_suffix('.tmp')
            with temp.open('wb') as raw:
                with gzip.GzipFile(filename='',fileobj=raw,mode='wb',compresslevel=6,mtime=0) as z:z.write(json.dumps(dict(schema=1,runs=runs),separators=(',',':')).encode())
            temp.replace(path);print(f'Published {path}: {path.stat().st_size} bytes',flush=True)
        except Exception as exc:
            print(f'{model}: {exc}',flush=True)
            if not previous:raise

if __name__=='__main__':main()
