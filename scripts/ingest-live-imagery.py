"""Independent measured radar reflectivity and licensed MTG GeoColour imagery."""
import base64
import datetime as dt
import io
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as et
from pathlib import Path

import h5py
import numpy as np
from PIL import Image
from pyproj import CRS, Transformer

NOW=dt.datetime.now(dt.timezone.utc)
DWD='https://opendata.dwd.de/weather/radar/composite/dmax/'
SAT='https://view.eumetsat.int/geoserver/mtg_fd/wms'
SAT_LAYER='mtg_fd:rgb_geocolour'  # EO:EUM:DAT:0913, CC BY 4.0
DBZ=[5,15,25,35,45,50,55,60]
COLORS=['#9acbff','#377ce5','#3bbc68','#d2e838','#f9a52b','#ed412e','#b70082','#6400aa']

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'WetterApp/1.0'}),timeout=45) as response:return response.read()

def timestamp(s):
    return dt.datetime.fromisoformat(s.replace('Z','+00:00'))

def text(v):return v.decode() if isinstance(v,bytes) else str(v)

def image_record(image, time, bounds, source):
    return dict(time=time.isoformat(),bounds=bounds,png=base64.b64encode(image).decode('ascii'),source=source)

def reflectivity():
    names=re.findall(r'href="(composite_dmax_(\d{8})_(\d{4})-hd5)"',get(DWD).decode())
    offers=sorted([(dt.datetime.strptime(date+hour,'%Y%m%d%H%M').replace(tzinfo=dt.timezone.utc),name) for name,date,hour in names],reverse=True)
    for time,name in offers[:3]:
        if not NOW-dt.timedelta(minutes=60)<=time<=NOW:continue
        try:
            with h5py.File(io.BytesIO(get(DWD+name)),'r') as h:
                where=h['where'].attrs;projection=CRS.from_user_input(text(where['projdef']));tr=Transformer.from_crs('EPSG:4326',projection,always_xy=True)
                data_group=None
                for ds in (h[k] for k in h if k.startswith('dataset')):
                    for g in (ds[k] for k in ds if k.startswith('data')):
                        w=g['what'].attrs
                        if text(w['quantity']).upper() in ('DBZH','DBZ','DBZV','DBZHC','DBZH_MAX'):data_group=g;break
                    if data_group is not None:break
                if data_group is None:raise ValueError('No reflectivity quantity found')
                w=data_group['what'].attrs;raw=data_group['data'][:];ny,nx=raw.shape
                if (nx,ny)!=(int(where['xsize']),int(where['ysize'])):raise ValueError('Unexpected radar shape')
                x0,y0=tr.transform(float(where['LL_lon']),float(where['LL_lat']))
                xs,ys=float(where['xscale']),float(where['yscale'])
                bounds=[2.,45.,18.,57.];width,height=800,600
                xx,yy=np.meshgrid(bounds[0]+(np.arange(width)+.5)/width*(bounds[2]-bounds[0]),bounds[3]-(np.arange(height)+.5)/height*(bounds[3]-bounds[1]))
                px,py=tr.transform(xx,yy);ix=np.floor((px-x0)/xs).astype(int);iy=ny-1-np.floor((py-y0)/ys).astype(int)
                inside=(ix>=0)&(ix<nx)&(iy>=0)&(iy<ny);v=raw[np.clip(iy,0,ny-1),np.clip(ix,0,nx-1)]
                valid=inside&(v!=w['nodata'])&(v!=w['undetect']);dbz=v.astype(float)*float(w['gain'])+float(w['offset'])
                rgba=np.zeros((height,width,4),dtype=np.uint8)
                for i,lower in enumerate(DBZ):
                    mask=valid&(dbz>=lower);color=bytes.fromhex(COLORS[i][1:]);rgba[mask]=[color[0],color[1],color[2],235]
                # All-transparent is valid only if measured coverage exists.
                if not inside.any():raise ValueError('No DWD radar coverage')
                buf=io.BytesIO();Image.fromarray(rgba,'RGBA').save(buf,format='PNG',optimize=True)
                print(f'DMAX {time.isoformat()} {nx}x{ny} dBZ',flush=True)
                return image_record(buf.getvalue(),time,bounds,'DWD DMAX · maximale Radarreflektivität')
        except Exception as e:print(f'DMAX {name}: {e}',flush=True)
    return None

def satellite():
    layer=None;service=SAT
    # Work on advertised metadata, never assume the current clock is image time.
    for endpoint in [SAT,'https://view.eumetsat.int/geoserver/wms']:
        try:
            xml=et.fromstring(get(endpoint+'?service=WMS&request=GetCapabilities&version=1.3.0'))
            for elem in xml.iter():elem.tag=elem.tag.split('}')[-1]
            layer=next((l for l in xml.iter('Layer') if (l.findtext('Name') or '').split(':')[-1]==SAT_LAYER.split(':')[-1] and (endpoint==SAT or (l.findtext('Name') or '').startswith('mtg_fd:'))),None)
            if layer is not None:service=endpoint;break
        except Exception as exc:print('GeoColour capabilities:',endpoint,exc,flush=True)
    if layer is None:
        print('Advertised GeoColour candidates:',[(l.findtext('Name'),l.findtext('Title')) for l in xml.iter('Layer') if 'geocolour' in ((l.findtext('Name') or '')+(l.findtext('Title') or '')).lower()][:10],flush=True)
        raise ValueError('Licensed GeoColour product not advertised')
    dim=next((d for d in layer.findall('Dimension') if d.get('name','').lower()=='time'),None)
    if dim is None:raise ValueError('No satellite time dimension')
    times=[]
    for token in re.findall(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z',(dim.text or '')+' '+dim.get('default','')):
        t=timestamp(token)
        if NOW-dt.timedelta(hours=3)<=t<=NOW:times.append(t)
    if not times:raise ValueError('No recent satellite observation')
    time=max(times);bounds=[-25.,34.,42.,71.];params=dict(service='WMS',version='1.1.1',request='GetMap',layers=layer.findtext('Name'),styles='',srs='EPSG:4326',bbox=','.join(map(str,bounds)),width=1000,height=600,format='image/png',transparent='true',time=time.strftime('%Y-%m-%dT%H:%M:%SZ'))
    image=get(service+'?'+urllib.parse.urlencode(params))
    if not image.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Satellite WMS returned no PNG')
    with Image.open(io.BytesIO(image)) as im:
        if im.size!=(1000,600):raise ValueError('Wrong satellite image size')
        im.verify()
    print('MTG GeoColour',time.isoformat(),flush=True)
    return image_record(image,time,bounds,'© EUMETSAT / NASA · MTG GeoColour · CC BY 4.0')

def main():
    out=Path('data/live-imagery.json');previous=json.loads(out.read_text()) if out.exists() else {}
    products={}
    for key,fetch,max_age in [('reflectivity',reflectivity,60),('satellite',satellite,180)]:
        try:
            item=fetch()
            if item:products[key]=item
        except Exception as exc:print(f'{key}: {exc}',flush=True)
        if key not in products and previous.get('products',{}).get(key):
            old=previous['products'][key]
            if NOW-timestamp(old['time'])<dt.timedelta(minutes=max_age):products[key]=old
    if not products:raise RuntimeError('No verified imagery available')
    payload=dict(schema=1,products=products)
    if payload!=previous:
        temporary=out.with_suffix('.tmp');temporary.write_text(json.dumps(payload,separators=(',',':')));temporary.replace(out)

if __name__=='__main__':main()
