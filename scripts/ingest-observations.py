"""DWD SYNOP BUFR station snapshots and RV analysis times (public Open Data)."""
import concurrent.futures
import base64
import datetime as dt
import gzip
import io
import json
import re
import urllib.request
import urllib.parse
from pathlib import Path

import eccodes as ec

ROOT='https://opendata.dwd.de/weather/'
NOW=dt.datetime.now(dt.timezone.utc)

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'WetterApp-Prototype/1.0'}),timeout=35) as f:
        return f.read()

def links(url):
    return re.findall(r'href="([^"<>]+)"',get(url).decode('utf-8'))


def radar_snapshot(times):
    """Get a verified PNG for a published RV time, independent of client CORS."""
    bounds=[2.0,45.0,18.0,57.0]
    for time in sorted(set(times),reverse=True)[:3]:
        if NOW-time>dt.timedelta(minutes=60):continue
        for layer in ('dwd:RV-Produkt','dwd:Niederschlagsradar'):
            try:
                params=dict(service='WMS',version='1.1.1',request='GetMap',layers=layer,styles='',srs='EPSG:4326',bbox=','.join(map(str,bounds)),width=800,height=600,format='image/png',transparent='true',time=time.strftime('%Y-%m-%dT%H:%M:%SZ'),exceptions='application/vnd.ogc.se_xml')
                image=get('https://maps.dwd.de/geoserver/dwd/wms?'+urllib.parse.urlencode(params))
                if not image.startswith(b'\x89PNG\r\n\x1a\n') or len(image)>2_000_000:raise ValueError('WMS returned no valid PNG')
                if int.from_bytes(image[16:20],'big')!=800 or int.from_bytes(image[20:24],'big')!=600:raise ValueError('Wrong radar image dimensions')
                return dict(time=time.isoformat(),bounds=bounds,png=base64.b64encode(image).decode('ascii'))
            except Exception as exc:print('RV image unavailable:',layer,time,exc,flush=True)
    return None

def read_synop(data):
    if data.startswith(b'\x1f\x8b'):data=gzip.decompress(data)
    # ecCodes consumes a real file object; use a temporary file for each batch.
    import tempfile
    with tempfile.TemporaryFile() as f:
        f.write(data);f.seek(0)
        while True:
            msg=ec.codes_bufr_new_from_file(f)
            if msg is None:break
            try:
                ec.codes_set(msg,'unpack',1)
                n=ec.codes_get_long(msg,'numberOfSubsets')
                def array(key):
                    try:
                        vals=ec.codes_get_array(msg,key)
                        # Do not guess alignment if a repeated descriptor has
                        # several values per subset.
                        return list(vals) if len(vals)==n else list(vals)*n if len(vals)==1 else [None]*n
                    except Exception:return [None]*n
                keys=['latitude','longitude','year','month','day','hour','minute','airTemperature','dewpointTemperature','windSpeed','windDirection','pressureReducedToMeanSeaLevel','stationOrSiteName','blockNumber','stationNumber']
                for row in zip(*(array(k) for k in keys)):
                    lat,lon,year,month,day,hour,minute,temp,dew,wind,direction,pressure,name,block,number=row
                    try:
                        time=dt.datetime(int(year),int(month),int(day),int(hour),int(minute),tzinfo=dt.timezone.utc)
                        if not NOW-dt.timedelta(minutes=95)<=time<=NOW+dt.timedelta(minutes=1):continue
                        if not 45<=lat<=56 or not 3<=lon<=17 or not 180<=temp<=340:continue
                        ident=f'{int(block):02}{int(number):03}' if block is not None and number is not None and 0<=number<=999 and 0<=block<=99 else f'{lat:.4f},{lon:.4f}'
                        r=dict(id=ident,name=str(name).strip() if name and str(name)!='MISSING' else ident,lat=float(lat),lon=float(lon),time=time.isoformat(),temp=round(float(temp)-273.15,1))
                        if dew is not None and 180<=dew<=340:r['dew']=round(float(dew)-273.15,1)
                        if wind is not None and 0<=wind<=100:r['wind']=round(float(wind)*3.6,1)
                        if direction is not None and 0<=direction<=360:r['direction']=float(direction)
                        if pressure is not None and 80000<=pressure<=110000:r['slp']=round(float(pressure)/100,1)
                        yield r
                    except (ValueError,TypeError,OverflowError):continue
            finally:ec.codes_release(msg)

def main():
    synop=ROOT+'weather_reports/synoptic/germany/'
    radar=ROOT+'radar/composite/rv/'
    result={'schema':1,'source':'Deutscher Wetterdienst (DWD) Open Data','generated':NOW.isoformat(),'stations':[]}
    try:
        times=[]
        for name in links(radar):
            m=re.fullmatch(r'composite_rv_(\d{8})_(\d{4})\.tar',name)
            if m:times.append(dt.datetime.strptime(''.join(m.groups()),'%Y%m%d%H%M').replace(tzinfo=dt.timezone.utc))
        times=[t for t in times if t<=NOW]
        if times:result['radarBase']=max(times).isoformat()
        print('RV base:',result.get('radarBase'),flush=True)
        snapshot=radar_snapshot(times)
        if snapshot:result['radarImage']=snapshot;print('RV image:',snapshot['time'],flush=True)
    except Exception as exc:print('RV listing unavailable:',exc,flush=True)
    try:
        names=[]
        for name in links(synop):
            m=re.search(r'Z__C_EDZW_(\d{14})_bda01',name)
            if m:
                t=dt.datetime.strptime(m[1],'%Y%m%d%H%M%S').replace(tzinfo=dt.timezone.utc)
                if NOW-dt.timedelta(minutes=110)<=t<=NOW:names.append((t,name))
        def read(item):
            try:return list(read_synop(get(urllib.parse.urljoin(synop,item[1]))))
            except Exception as exc:print('SYNOP file error:',str(exc)[:200],flush=True);return []
        latest={}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for records in pool.map(read,sorted(names,reverse=True)[:25]):
                for s in records:
                    if s['id'] not in latest or s['time']>latest[s['id']]['time']:latest[s['id']]=s
        result['stations']=sorted(latest.values(),key=lambda s:s['id'])
        print('Stations:',len(result['stations']),flush=True)
    except Exception as exc:print('SYNOP unavailable:',exc,flush=True)
    if not result.get('radarBase') and not result['stations']:raise RuntimeError('No current DWD data available')
    output=Path('data/stations.json');output.parent.mkdir(exist_ok=True)
    if output.exists() and not result.get('radarImage'):
        try:
            previous=json.loads(output.read_text()).get('radarImage')
            if previous and NOW-dt.datetime.fromisoformat(previous['time'])<dt.timedelta(minutes=60):result['radarImage']=previous
        except (ValueError,TypeError,KeyError):pass
    output.write_text(json.dumps(result,separators=(',',':')),encoding='utf8')

if __name__=='__main__':main()
