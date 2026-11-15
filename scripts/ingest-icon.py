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
         "cape_ml":("mlcape",1,0,1),"cin_ml":("mlcin",1,0,1),
         "vis":("visibility",.001,0,.1),"tqv":("pwat",1,0,.1),
         "relhum_2m":("rh2",1,0,.1),"clcl":("lowcloud",1,0,.1),
         "clcm":("midcloud",1,0,.1),"clch":("highcloud",1,0,.1),
         "t_g":("tground",1,-273.15,.1),"snowlmt":("snowline",1,0,1),
         "hzerocl":("freezing",1,0,1),"ww":("ww",1,0,1)}
FILENAME = re.compile(r'href="([^"]*regular-lat-lon_single-level_(\d{10})_(\d{3})[^"]*\.grib2\.bz2)"')
PRESSURE_FILENAME = re.compile(r'href="([^"]*regular-lat-lon_pressure-level_(\d{10})_(\d{3})_(\d+)_.*\.grib2\.bz2)"')
PRESSURE = {"t":{850:("t850",1,-273.15),700:("t700",1,-273.15),500:("t500",1,-273.15)},
            "relhum":{850:("rh850",1,0),700:("rh700",1,0),500:("rh500",1,0)},
            "fi":{500:("z500",1/98.0665,0)},"u":{300:("u300",1,0)},"v":{300:("v300",1,0)}}


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


def choose_run(model, hours):
    """Find newest complete cycle, only using the same initialization stamp."""
    now = dt.datetime.now(dt.timezone.utc)
    runs = [(now - dt.timedelta(hours=i)).strftime("%H") for i in range(24) if (now.hour-i) % 6 == 0]
    for run in runs:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                offers = dict(zip(VARIABLES, pool.map(lambda v: listing(model, run, v), VARIABLES)))
        except Exception as exc:
            print(f"{model} {run}: directory unavailable: {exc}", flush=True)
            continue
        stamps = sorted({stamp for stamp, _ in offers["t_2m"]}, reverse=True)
        for stamp in stamps:
            start = dt.datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
            if not now - dt.timedelta(hours=48) <= start <= now:
                continue
            if all((stamp, h) in offers[v] for v in VARIABLES for h in hours if not (v=="tot_prec" and h==0)):
                return stamp, offers
    raise RuntimeError(f"No complete recent {model} run available")


def target_grid(config):
    west, east, south, north = config["bounds"]
    delta = config["delta"]
    x = west + np.arange(int(round((east-west)/delta))+1)*delta
    y = south + np.arange(int(round((north-south)/delta))+1)*delta
    return x, y


def sample_grib(blob, x, y, stamp, hour):
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
            xi=np.abs(xx[None,:]-x[:,None]).argmin(axis=1)
            yi=np.abs(yy[None,:]-y[:,None]).argmin(axis=1)
            out=vals[np.ix_(yi,xi)].astype(float)
            out[(y<yy.min()-1e-5)|(y>yy.max()+1e-5),:]=np.nan
            out[:,(x<xx.min()-1e-5)|(x>xx.max()+1e-5)]=np.nan
            missing=ec.codes_get_double(gid,"missingValue")
            out[(out==missing)|(~np.isfinite(out))|(np.abs(out)>1e8)]=np.nan
            return out
        finally:
            ec.codes_release(gid)


def pack(values, scale):
    scaled=np.rint(values/scale)
    valid=np.isfinite(scaled)&(scaled>=-32767)&(scaled<=32767)
    encoded=np.where(valid,scaled,-32768).astype("<i2")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def model_data(model):
    cfg=MODELS[model]; hours=cfg["hours"]; x,y=target_grid(cfg)
    stamp,offers=choose_run(model,hours)
    def optional_listing(v):
        try: return v,listing(model,stamp[-2:],v)
        except Exception as exc:
            print(f"Optional {model} {v}: {exc}",flush=True);return v,{}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        extra_offers=dict(pool.map(optional_listing,EXTRA))
    def pressure_offer(v):
        try:return v,pressure_listing(model,stamp[-2:],v)
        except Exception as exc:
            print(f"Optional pressure {model} {v}: {exc}",flush=True);return v,{}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pressure_offers=dict(pool.map(pressure_offer,PRESSURE))
    print(f"{model}: {stamp} · {len(hours)} steps",flush=True)
    frames={}
    for hour in hours:
        def get(variable):
            if variable=="tot_prec" and hour==0:
                return variable,None
            return variable,sample_grib(download(offers[variable][stamp,hour]),x,y,stamp,hour)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            fields=dict(pool.map(get,VARIABLES))
        temp=fields["t_2m"]-273.15
        dew=fields["td_2m"]-273.15
        precip=fields["tot_prec"]
        if precip is None:
            precip=np.where(np.isfinite(temp),0,np.nan)
        # Preserve true cumulative values; interval amounts are differences.
        frames[str(hour)]={key:pack(value,scale) for key,value,scale in (
            ("temp2",temp,.1),("dew",dew,.1),("wind",np.hypot(fields["u_10m"],fields["v_10m"])*3.6,.1),
            ("slp",fields["pmsl"]/100,.1),("rainTotal",precip,.1),("cloud",fields["clct"],.1),
        )}
        # Meteorological direction (direction from which the wind blows).
        frames[str(hour)]["winddir"]=pack((np.degrees(np.arctan2(-fields["u_10m"],-fields["v_10m"]))+360)%360,.1)
        def extra_field(variable):
            url=extra_offers[variable].get((stamp,hour))
            if not url:return None
            try:
                key,factor,offset,scale=EXTRA[variable]
                values=sample_grib(download(url),x,y,stamp,hour)
                return key,pack(values*factor+offset,scale)
            except Exception as exc:
                print(f"Optional {model} {variable} +{hour}: {exc}",flush=True);return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(extra_field,EXTRA):
                if result:frames[str(hour)][result[0]]=result[1]
        def pressure_field(entry):
            variable,level,spec=entry
            url=pressure_offers[variable].get((stamp,hour,level))
            if not url:return None
            try:
                key,factor,offset=spec
                values=sample_grib(download(url),x,y,stamp,hour)
                return key,values*factor+offset
            except Exception as exc:
                print(f"Optional pressure {model} {variable} {level} +{hour}: {exc}",flush=True);return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            pressure=dict(r for r in pool.map(pressure_field,[(v,l,s) for v,levels in PRESSURE.items() for l,s in levels.items()]) if r)
        if 'u300' in pressure and 'v300' in pressure:
            pressure['jet']=np.hypot(pressure.pop('u300'),pressure.pop('v300'))
        for key,value in pressure.items():
            if key not in ('u300','v300'):frames[str(hour)][key]=pack(value,.1)
        if not np.isfinite(temp).any():
            raise ValueError("Empty temperature field")
        print(f"{model} +{hour:03d}h",flush=True)
    start=dt.datetime.strptime(stamp,"%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
    return dict(schema=1,model=cfg["name"],source="Deutscher Wetterdienst (DWD) Open Data",sourceUrl=f"{ROOT}/{model}/",run=start.isoformat(),generated=dt.datetime.now(dt.timezone.utc).isoformat(),grid=dict(west=float(x[0]),south=float(y[0]),step=cfg["delta"],nx=len(x),ny=len(y),scale=.1,missing=-32768),scales={key:scale for key,_,_,scale in EXTRA.values()},hours=hours,frames=frames)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",default="data");parser.add_argument("--models",nargs="+",choices=MODELS,default=list(MODELS));args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    # Build all outputs first, so a failed model cannot replace only half.
    data={model:model_data(model) for model in args.models}
    for model,payload in data.items():
        path=output/f"{model}.json";temp=path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload,separators=(",",":")),encoding="utf8");os.replace(temp,path)


if __name__=="__main__":
    main()
