"""Create compact, georeferenced forecast grids from DWD GRIB2 Open Data.

Run with Python, eccodes and numpy. These are derived sample grids, not
native-resolution products. Never publish an incomplete or mixed model run.
"""
import argparse
import base64
import bz2
import concurrent.futures
import datetime as dt
import json
import os
import re
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = "https://opendata.dwd.de/weather/nwp"
MODELS = {
    "icon-d2": dict(name="ICON-D2", hours=list(range(0, 49, 3)), bounds=(3.8, 16.7, 46.3, 55.8), delta=.10),
    "icon-eu": dict(name="ICON-EU", hours=list(range(0, 121, 6)), bounds=(-25, 42, 34, 71), delta=.40),
}
# Source variable names and output units. Accumulation stays in kg/m² = mm.
VARIABLES = ("t_2m", "td_2m", "u_10m", "v_10m", "pmsl", "tot_prec", "clct")
# Optional products: do not invalidate a working base forecast if a field
# is absent from a particular cycle/step. All output uses explicit units.
EXTRA = {"vmax_10m":("gust",3.6,0,.1),"h_snow":("snowdepth",100,0,.1),
         "w_snow":("snowWater",1,0,.1),"rho_snow":("snowDensity",1,0,1),
         "snow_gsp":("snowGspTotal",1,0,.1),"snow_con":("snowConTotal",1,0,.1),
         "cape_ml":("mlcape",1,0,1),"cin_ml":("mlcin",1,0,1),
         "vis":("visibility",.001,0,.1),"tqv":("pwat",1,0,.1),
         "relhum_2m":("rh2",1,0,.1),"clcl":("lowcloud",1,0,.1),
         "clcm":("midcloud",1,0,.1),"clch":("highcloud",1,0,.1),
         "t_g":("tground",1,-273.15,.1),"snowlmt":("snowline",1,0,1),
         "hzerocl":("freezing",1,0,1),"ww":("ww",1,0,1),
         "tmax_2m":("tmax",1,-273.15,.1),"tmin_2m":("tmin",1,-273.15,.1),
         "t_snow":("tsnow",1,-273.15,.1),"t_5cm":("ground",1,-273.15,.1),
         "bas_con":("cloudbase",1,0,1),"top_con":("cloudtop",1,0,1),
         "htop_dc":("deepcloudtop",1,0,1),"cape_mu":("mucape",1,0,1),
         "cin_mu":("mucin",1,0,1)}
FILENAME = re.compile(r'href="([^"]*regular-lat-lon_single-level_(\d{10})_(\d{3})[^"]*\.grib2\.bz2)"')
PRESSURE_FILENAME = re.compile(r'href="([^"]*regular-lat-lon_pressure-level_(\d{10})_(\d{3})_(\d+)_.*\.grib2\.bz2)"')
LEVELS=(925,850,700,500,300,250,200)
PRESSURE = {"t":{n:(f"t{n}",1,-273.15) for n in LEVELS},
            "relhum":{n:(f"rh{n}",1,0) for n in LEVELS},
            "fi":{n:(f"z{n}",1/98.0665,0) for n in LEVELS},
            "u":{n:(f"u{n}",1,0) for n in LEVELS},"v":{n:(f"v{n}",1,0) for n in LEVELS}}


def download(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "WetterApp-Prototype/1.0"}), timeout=45) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def listing(model, run, variable):
    directory = f"{ROOT}/{model}/grib/{run}/{variable}/"
    return {(stamp, int(hour)): directory + name for name, stamp, hour in FILENAME.findall(download(directory).decode("utf8"))}


def pressure_listing(model, run, variable):
    directory = f"{ROOT}/{model}/grib/{run}/{variable}/"
    return {(stamp,int(hour),int(level)):directory+name for name,stamp,hour,level in PRESSURE_FILENAME.findall(download(directory).decode("utf8"))}


def choose_run(model, hours, now=None, source=None):
    """Select newest COMPLETE initialization by date, then hour.

    DWD directories are keyed only by UTC hour and may contain yesterday's
    complete cycle while today's cycle is still uploading.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    source = source or listing
    cycle=3 if model=='icon-d2' else 6
    base=now.replace(hour=now.hour//cycle*cycle,minute=0,second=0,microsecond=0)
    by_hour={}
    for lag in range(0,49,cycle):
        candidate=base-dt.timedelta(hours=lag)
        if now-candidate>dt.timedelta(hours=48):break
        run=candidate.strftime('%H');stamp=candidate.strftime('%Y%m%d%H')
        if run not in by_hour:
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                    by_hour[run]=dict(zip(VARIABLES,pool.map(lambda v:source(model,run,v),VARIABLES)))
            except Exception as exc:
                print(f"{model} {run}: directory unavailable: {exc}",flush=True)
                by_hour[run]={}
        offers=by_hour[run]
        if offers and all((stamp,h) in offers[v] for v in VARIABLES for h in hours if not (v=='tot_prec' and h==0)):
            print(f'{model}: newest complete initialization {stamp}',flush=True)
            return stamp,offers
    raise RuntimeError(f"No complete recent {model} run available")


def target_grid(config):
    west, east, south, north = config["bounds"]
    delta = config["delta"]
    x = west + np.arange(int(round((east-west)/delta))+1)*delta
    y = south + np.arange(int(round((north-south)/delta))+1)*delta
    return x, y


def sample_grib(blob, x, y, stamp, hour, interval=None):
    import eccodes as ec
    with tempfile.TemporaryFile() as f:
        f.write(bz2.decompress(blob));f.seek(0)
        gid=ec.codes_grib_new_from_file(f)
        if gid is None:
            raise ValueError("No GRIB2 message")
        try:
            if ec.codes_get(gid,"gridType")!="regular_ll":
                raise ValueError("Expected regular latitude-longitude GRIB")
            actual = f"{ec.codes_get_long(gid,'dataDate'):08d}{ec.codes_get_long(gid,'dataTime')//100:02d}"
            if actual != stamp or ec.codes_get_long(gid,"endStep")!=hour:
                raise ValueError(f"Wrong run/step: {actual}, {ec.codes_get(gid,'endStep')}")
            if interval is not None:
                start,kind=interval
                if ec.codes_get_long(gid,'startStep')!=start or ec.codes_get(gid,'stepType')!=kind:
                    raise ValueError(f'Unexpected extrema interval at +{hour}: {ec.codes_get(gid,"stepRange")}')
            ni,nj=ec.codes_get_long(gid,"Ni"),ec.codes_get_long(gid,"Nj")
            vals=ec.codes_get_values(gid)
            lat=ec.codes_get_array(gid,"latitudes")
            lon=(ec.codes_get_array(gid,"longitudes")+180)%360-180
            if ec.codes_get_long(gid,"jPointsAreConsecutive"):
                vals,lat,lon=[a.reshape(ni,nj).T for a in (vals,lat,lon)]
            else:
                vals,lat,lon=[a.reshape(nj,ni) for a in (vals,lat,lon)]
            if ec.codes_get_long(gid,"alternativeRowScanning"):
                raise ValueError("Unsupported alternating scan layout")
            xx,yy=lon[0,:],lat[:,0]
            if not (np.allclose(lon,xx[None,:]) and np.allclose(lat,yy[:,None])):
                raise ValueError("Grid coordinate axes not rectangular")
            missing=ec.codes_get_double(gid,"missingValue")
            if x is None and y is None:
                # Preserve the actual published DWD grid, including its origin
                # and spacing; never regrid an already high-resolution field.
                ix,iy=np.argsort(xx),np.argsort(yy)
                out=vals[np.ix_(iy,ix)].astype(float)
                out[(out==missing)|(~np.isfinite(out))|(np.abs(out)>1e8)]=np.nan
                return xx[ix],yy[iy],out
            xi=np.abs(xx[None,:]-x[:,None]).argmin(axis=1)
            yi=np.abs(yy[None,:]-y[:,None]).argmin(axis=1)
            out=vals[np.ix_(yi,xi)].astype(float)
            out[(y<yy.min()-1e-5)|(y>yy.max()+1e-5),:]=np.nan
            out[:,(x<xx.min()-1e-5)|(x>xx.max()+1e-5)]=np.nan
            out[(out==missing)|(~np.isfinite(out))|(np.abs(out)>1e8)]=np.nan
            return out
        finally:
            ec.codes_release(gid)


def pack(values, scale):
    scaled=np.rint(values/scale)
    valid=np.isfinite(scaled)&(scaled>=-32767)&(scaled<=32767)
    encoded=np.where(valid,scaled,-32768).astype("<i2")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def model_data(model,selected=None,native=False,sink=None,core_hours=None):
    cfg=MODELS[model]; hours=cfg["hours"]; x,y=target_grid(cfg)
    stamp,offers=selected or choose_run(model,hours)
    if native:
        xx,yy,_=sample_grib(download(offers['t_2m'][stamp,0]),None,None,stamp,0)
        west,east,south,north=cfg['bounds']
        x=xx[(xx>=west-1e-5)&(xx<=east+1e-5)];y=yy[(yy>=south-1e-5)&(yy<=north+1e-5)]
    grid=dict(west=float(x[0]),south=float(y[0]),step=float(x[1]-x[0]) if native else cfg['delta'],nx=len(x),ny=len(y),scale=.1,missing=-32768)
    if native and (not np.allclose(np.diff(x),grid['step'],atol=1e-6) or not np.allclose(np.diff(y),grid['step'],atol=1e-6)):raise ValueError('Nonuniform native grid')
    def read(blob,hh,interval=None):
        if not native:return sample_grib(blob,x,y,stamp,hh,interval)
        xx,yy,values=sample_grib(blob,None,None,stamp,hh,interval)
        ix=np.searchsorted(xx,x-1e-6);iy=np.searchsorted(yy,y-1e-6)
        if (ix>=len(xx)).any() or (iy>=len(yy)).any() or not np.allclose(xx[ix],x,rtol=0,atol=1e-6) or not np.allclose(yy[iy],y,rtol=0,atol=1e-6):raise ValueError('Native field grid differs')
        if not np.isclose(xx[1]-xx[0],grid['step'],rtol=0,atol=1e-6) or not np.isclose(yy[1]-yy[0],grid['step'],rtol=0,atol=1e-6):raise ValueError('Native field resolution differs')
        return values[np.ix_(iy,ix)]
    # More low-level pressure surfaces are essential for AGL wind/parcel
    # profiles. Keep the large legacy European snapshot within its size cap.
    detailed=native and (model=='icon-d2' or cfg['bounds'][0]>0)
    extras={**EXTRA,**({'ps':('ps',.01,0,.1)} if native else {})}
    pressure_specs={v:dict(levels) for v,levels in PRESSURE.items()}
    if detailed:
        for v,levels in pressure_specs.items():
            key,fac,offset=levels[850]
            levels.update({n:(key[:-3]+str(n),fac,offset) for n in (1000,975,950,900,800,600,400)})
    orog=None
    if native:
        try:
            directory=f'{ROOT}/{model}/grib/{stamp[-2:]}/hsurf/'
            matches=re.findall(r'href="([^"]*regular-lat-lon_time-invariant_(\d{10})[^"]*\.grib2\.bz2)"',download(directory).decode('utf8'))
            name=next(name for name,cycle in matches if cycle==stamp)
            orog=read(download(directory+name),0)
        except Exception as exc:print(f'Optional {model} model terrain: {exc}',flush=True)
    def optional_listing(v):
        try: return v,listing(model,stamp[-2:],v)
        except Exception as exc:
            print(f"Optional {model} {v}: {exc}",flush=True);return v,{}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        extra_offers=dict(pool.map(optional_listing,extras))
    def pressure_offer(v):
        try:return v,pressure_listing(model,stamp[-2:],v)
        except Exception as exc:
            print(f"Optional pressure {model} {v}: {exc}",flush=True);return v,{}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pressure_offers=dict(pool.map(pressure_offer,pressure_specs))
    print(f"{model}: {stamp} · {len(hours)} steps",flush=True)
    frames={}
    for hour in hours:
        core=core_hours is None or hour in core_hours
        def get(variable):
            if variable=="tot_prec" and hour==0:
                return variable,None
            if not core and (stamp,hour) not in offers[variable]:return variable,None
            return variable,read(download(offers[variable][stamp,hour]),hour)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            fields=dict(pool.map(get,VARIABLES))
        temp=fields["t_2m"]-273.15 if fields['t_2m'] is not None else None
        dew=fields["td_2m"]-273.15 if fields['td_2m'] is not None else None
        precip=fields["tot_prec"]
        if hour==0 and precip is None:
            precip=np.where(np.isfinite(temp),0,np.nan)
        wind=fields['u_10m'] is not None and fields['v_10m'] is not None
        # Preserve true cumulative values; interval amounts are differences.
        frames[str(hour)]={key:pack(value,scale) for key,value,scale in (
            ("temp2",temp,.1),("dew",dew,.1),("wind",np.hypot(fields["u_10m"],fields["v_10m"])*3.6 if wind else None,.1),
            ("slp",fields["pmsl"]/100 if fields['pmsl'] is not None else None,.1),("rainTotal",precip,.1),("cloud",fields["clct"],.1),
        ) if value is not None}
        # Meteorological direction (direction from which the wind blows).
        if wind:frames[str(hour)]["winddir"]=pack((np.degrees(np.arctan2(-fields["u_10m"],-fields["v_10m"]))+360)%360,.1)
        if orog is not None:frames[str(hour)]['orog']=pack(orog,1)
        def extra_field(variable):
            url=extra_offers[variable].get((stamp,hour))
            if not url:return None
            try:
                key,factor,offset,scale=extras[variable]
                if key in ('tmin','tmax') and hour==0:return None
                interval=((hour-1)//6*6,'min' if key=='tmin' else 'max') if key in ('tmin','tmax') else None
                values=read(download(url),hour,interval)
                return key,pack(values*factor+offset,scale)
            except Exception as exc:
                print(f"Optional {model} {variable} +{hour}: {exc}",flush=True);return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(extra_field,extras):
                if result:frames[str(hour)][result[0]]=result[1]
        def pressure_field(entry):
            variable,level,spec=entry
            url=pressure_offers[variable].get((stamp,hour,level))
            if not url:return None
            try:
                key,factor,offset=spec
                values=read(download(url),hour)
                return key,values*factor+offset
            except Exception as exc:
                print(f"Optional pressure {model} {variable} {level} +{hour}: {exc}",flush=True);return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            pressure=dict(r for r in pool.map(pressure_field,[(v,l,s) for v,levels in pressure_specs.items() for l,s in levels.items()]) if r)
        if 'u300' in pressure and 'v300' in pressure:
            pressure['jet']=np.hypot(pressure['u300'],pressure['v300'])
        for low,key in [(850,'lapse'),(700,'lapse7')]:
            if all(k in pressure for k in (f't{low}','t500',f'z{low}','z500')):
                thickness=(pressure['z500']-pressure[f'z{low}'])/100
                pressure[key]=np.divide(pressure[f't{low}']-pressure['t500'],thickness,out=np.full_like(thickness,np.nan),where=thickness>0)
        for key,value in pressure.items():
            frames[str(hour)][key]=pack(value,.1)
        if core and (temp is None or not np.isfinite(temp).any()):
            raise ValueError("Empty temperature field")
        if sink is not None:sink(grid,hour,frames.pop(str(hour)),{**{key:scale for key,_,_,scale in extras.values()},'orog':1})
        print(f"{model} +{hour:03d}h",flush=True)
    start=dt.datetime.strptime(stamp,"%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
    return dict(schema=1,model=cfg["name"],source="Deutscher Wetterdienst (DWD) Open Data",sourceUrl=f"{ROOT}/{model}/",run=start.isoformat(),generated=dt.datetime.now(dt.timezone.utc).isoformat(),grid=grid,scales={key:scale for key,_,_,scale in EXTRA.values()},extremaWindowHours=6,hours=hours,frames=frames)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",default="data");parser.add_argument("--models",nargs="+",choices=MODELS,default=list(MODELS));args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    # Build all outputs first, so a failed model cannot replace only half.
    for model in args.models:
        path=output/f"{model}.json";temp=path.with_suffix(".tmp")
        selected=choose_run(model,MODELS[model]['hours'])
        if path.exists() and dt.datetime.fromisoformat(json.loads(path.read_text())['run']).strftime('%Y%m%d%H')>=selected[0]:
            print(f'{model}: newest run already published',flush=True);continue
        payload=model_data(model,selected)
        temp.write_text(json.dumps(payload,separators=(",",":")),encoding="utf8");os.replace(temp,path)


if __name__=="__main__":
    main()

