"""Build native hourly location forecasts directly from DWD GRIB2 Open Data.

Use the same original coordinates for every field, including precipitation,
temperature, wind, humidity and visibility. No weather stations or regridding.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import runpy
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np

HERE=Path(__file__).parent
API=runpy.run_path(str(HERE/'ingest-icon.py'))
PointTiles=runpy.run_path(str(HERE/'native-point.py'))['PointTiles']
CORE=API['VARIABLES']
# Optional DWD single-level fields; absent fields never substitute zero.
EXTRA={k:v for k,v in API['EXTRA'].items() if k in {
    'vmax_10m','h_snow','vis','relhum_2m','clcl','clcm','clch','t_g','t_5cm',
    'ww','tmin_2m','tmax_2m','t_snow','snowlmt','hzerocl','cape_ml','cin_ml',
    'cape_mu','cin_mu','tqv','bas_con','top_con','htop_dc'}}
EXTRA['vis']=('visibility',.001,0,.01)  # 10 m precision for dense-fog thresholds
HOURLY={'vmax_10m','h_snow','vis','relhum_2m','clcl','t_g','t_5cm','ww','tmin_2m','tmax_2m'}

def build(model,stamp,offers,hours,output):
    run=dt.datetime.strptime(stamp,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc).isoformat()
    gen=dt.datetime.now(dt.timezone.utc).isoformat()
    def listing(v):
        try: return v,API['listing'](model,stamp[-2:],v)
        except Exception as exc: print(f'{v}: {exc}',flush=True);return v,{}
    with cf.ThreadPoolExecutor(max_workers=5) as pool: extra=dict(pool.map(listing,EXTRA))
    x,y,_=API['sample_grib'](API['download'](offers['t_2m'][stamp,0]),None,None,stamp,0)
    west,east,south,north=API['MODELS'][model]['bounds']
    # Include the border cell for nearest-coordinate selection.
    ix=np.flatnonzero((x>=west-abs(x[1]-x[0]))&(x<=east+abs(x[1]-x[0])))
    iy=np.flatnonzero((y>=south-abs(y[1]-y[0]))&(y<=north+abs(y[1]-y[0])))
    xx,yy=x[ix],y[iy];step=float(xx[1]-xx[0])
    if not np.allclose(np.diff(xx),step,atol=1e-6) or not np.allclose(np.diff(yy),step,atol=1e-6):raise ValueError('Irregular native grid')
    grid=dict(west=float(xx[0]),south=float(yy[0]),step=step,nx=len(xx),ny=len(yy),scale=.1,missing=-32768)
    writer=PointTiles(output,API['MODELS'][model]['name'],run,gen,hours,extrema=6,quick=True)
    scales={k:s for k,_,_,s in EXTRA.values()}
    def read(url,h,interval=None):
        a,b,v=API['sample_grib'](API['download'](url),None,None,stamp,h,interval)
        if not np.array_equal(a,x) or not np.array_equal(b,y): raise ValueError('Native grid mismatch')
        return v[np.ix_(iy,ix)]
    with cf.ThreadPoolExecutor(max_workers=5) as pool:
        for h in hours:
            def core(v): return v,None if v=='tot_prec' and h==0 else read(offers[v][stamp,h],h)
            values=dict(pool.map(core,CORE));t=values['t_2m']-273.15;u,v=values['u_10m'],values['v_10m']
            rain=values['tot_prec'] if h else np.where(np.isfinite(t),0,np.nan)
            arrays=dict(temp2=t,dew=values['td_2m']-273.15,wind=np.hypot(u,v)*3.6,
                        winddir=(np.degrees(np.arctan2(-u,-v))+360)%360,slp=values['pmsl']/100,cloud=values['clct'],rainTotal=rain)
            def optional(var):
                if var not in HOURLY and h%3:return None
                if not h and var in ('tmin_2m','tmax_2m'):return None
                url=extra[var].get((stamp,h))
                if not url:return None
                key,factor,offset,_=EXTRA[var]
                interval=((h-1)//6*6,'min' if var=='tmin_2m' else 'max') if var in ('tmin_2m','tmax_2m') else None
                try:return key,read(url,h,interval)*factor+offset
                except Exception as exc:print(f'{var} +{h}: {exc}',flush=True);return None
            arrays.update(r for r in pool.map(optional,EXTRA) if r)
            if 'rh2' not in arrays:
                td=arrays['dew'];arrays['rh2']=np.clip(100*np.exp(17.625*td/(243.04+td)-17.625*t/(243.04+t)),0,100)
            writer.add(grid,h,{k:API['pack'](a,scales.get(k,.1)) for k,a in arrays.items()},scales)
            print(f'{model} {stamp} +{h:02d}: {len(arrays)} fields',flush=True)
    writer.finish()

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',choices=API['MODELS'],required=True);p.add_argument('--output',required=True);p.add_argument('--max-steps',type=int);args=p.parse_args()
    hours=list(range(49));stamp,offers=API['choose_run'](args.model,hours)
    if args.max_steps:hours=hours[:args.max_steps]
    build(args.model,stamp,offers,hours,args.output)
    if args.max_steps:return
    # An older cycle covering local midnight supplies the elapsed half of Today.
    run=dt.datetime.strptime(stamp,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc)
    midnight=dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo('Europe/Berlin')).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(dt.timezone.utc)
    if run>midnight:
        try:
            past,offers=API['choose_run'](args.model,list(range(49)),now=midnight)
            start=dt.datetime.strptime(past,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc)
            last=min(48,int((run-start).total_seconds()/3600)+6)
            build(args.model,past,offers,list(range(last+1)),Path(args.output)/'anchor')
        except Exception as exc:print(f'Anchor unavailable: {exc}; latest forecast remains valid',flush=True)

if __name__=='__main__':main()
