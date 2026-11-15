"""DWD SYNOP BUFR station snapshots and RV analysis times (public Open Data)."""
import concurrent.futures
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
    output=Path('data/stations.json');output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(result,separators=(',',':')),encoding='utf8')

if __name__=='__main__':main()
