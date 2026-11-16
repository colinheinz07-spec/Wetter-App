"""Extract original published 2 m temperature grids from ECMWF and NOAA GRIB."""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import runpy
import time
import urllib.parse
from pathlib import Path

import eccodes as ec
import numpy as np

HERE=Path(__file__).parent
N=runpy.run_path(str(HERE/'native-temperature.py'))
pack=runpy.run_path(str(HERE/'ingest-icon.py'))['pack']

def decode(blob, run, h):
    gid=ec.codes_new_from_message(blob)
    try:
        stamp=f"{ec.codes_get_long(gid,'dataDate'):08d}{ec.codes_get_long(gid,'dataTime')//100:02d}"
        if stamp!=run.strftime('%Y%m%d%H') or ec.codes_get_long(gid,'endStep')!=h:raise ValueError('Mixed model run/lead')
        if ec.codes_get(gid,'gridType')!='regular_ll' or ec.codes_get_long(gid,'alternativeRowScanning'):raise ValueError('Unexpected grid')
        ni,nj=ec.codes_get_long(gid,'Ni'),ec.codes_get_long(gid,'Nj')
        arrays=[ec.codes_get_values(gid),ec.codes_get_array(gid,'latitudes'),(ec.codes_get_array(gid,'longitudes')+180)%360-180]
        val,lat,lon=[a.reshape(ni,nj).T if ec.codes_get_long(gid,'jPointsAreConsecutive') else a.reshape(nj,ni) for a in arrays]
        x,y=lon[0],lat[:,0]
        if not np.allclose(lon,x[None,:]) or not np.allclose(lat,y[:,None]):raise ValueError('Nonrectangular coordinates')
        ix=np.argsort(x);iy=np.argsort(y)
        ix=ix[(x[ix]>=-25.25)&(x[ix]<=42.25)];iy=iy[(y[iy]>=33.75)&(y[iy]<=71.25)]
        v=val[np.ix_(iy,ix)].astype(float)
        v[(v==ec.codes_get_double(gid,'missingValue'))|(~np.isfinite(v))|(np.abs(v)>1e8)]=np.nan
        units=ec.codes_get(gid,'units')
        if units not in ('K','Kelvin'):raise ValueError(f'Unexpected temperature unit: {units}')
        return x[ix],y[iy],v-273.15
    finally:ec.codes_release(gid)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',choices=('ifs','ifs-short','aifs','aifs-ens-control','gfs'),required=True)
    model=parser.parse_args().model
    d=json.loads(Path(f'data/{model}.json').read_text())
    run=dt.datetime.fromisoformat(d['run']);hours=d['hours'];root=Path('data')/(model+'-temperature')
    if N['already'](root,d['run'],hours):return
    if model=='gfs':
        api=runpy.run_path(str(HERE/'ingest-gfs.py'))
        def download(h):
            params=dict(file=api['filename'](run,h),dir=f'/gfs.{run:%Y%m%d}/{run:%H}/atmos',subregion='',leftlon=-25.25,rightlon=42.25,toplat=71.25,bottomlat=33.75,var_TMP='on',lev_2_m_above_ground='on')
            url=api['ROOT']+'?'+urllib.parse.urlencode(params)
            for attempt in range(3):
                time.sleep(10)
                try:return api['get'](url)
                except Exception:
                    if attempt==2:raise
        workers=1
    else:
        api=runpy.run_path(str(HERE/'ingest-ifs.py'))
        api['file_base'].__globals__['PRODUCT']='ifs' if model=='ifs-short' else model
        def download(h):
            rows=api['index'](run,h)
            matches=[row for row in rows if row.get('levtype')=='sfc' and row.get('param')=='2t']
            if len(matches)!=1:raise ValueError(f'No unique 2t message +{h}')
            row=matches[0]
            return api['get'](api['file_base'](run,h)+'.grib2',int(row['_offset']),int(row['_length']))
        workers=4
    def read(h):return h,decode(download(h),run,h)
    grid=None;tiles={};maps={}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for h,(x,y,v) in pool.map(read,hours):
            g=N['grid_for'](x,y)
            if grid is not None and g!=grid:raise ValueError('Native coordinates changed')
            grid=g;N['add_frame'](tiles,grid,h,'temp2',v,pack);maps[h]=pack(v,.1)
            print(f'{model} +{h} native {grid["nx"]}×{grid["ny"]}',flush=True)
    N['publish'](root,d['model'],d['run'],hours,grid,tiles,maps)
if __name__=='__main__':main()
