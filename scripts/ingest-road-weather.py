"""Create a compact DWD SWSMOS road-weather snapshot for the mobile UI.

Official SWSMOS is a station-based road forecast. Never interpolate the
categorical RC codes as if they described every nearby street.
"""
import bz2
import csv
import datetime as dt
import io
import json
import re
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE = "https://opendata.dwd.de/weather/local_forecasts/swsmos/"
HEADERS = {"ID", "YYYYMMDDHHMM", "TL", "RC", "TS"}
UTC = dt.timezone.utc

def fetch(name):
    req=urllib.request.Request(BASE+name,headers={"User-Agent":"WetterApp/1.0 (OpenData SWSMOS)"})
    with urllib.request.urlopen(req,timeout=45) as resp:
        return resp.read()

def norm(s):
    return re.sub(r'[^A-Z0-9]', '', ''.join(c for c in unicodedata.normalize('NFKD',s.upper()) if not unicodedata.combining(c)))

def records(blob,expect=None):
    decoded=bz2.decompress(blob).decode('utf-8-sig',errors='replace')
    lines=[line for line in decoded.splitlines() if line.strip() and not line.lstrip().startswith(('#','//'))]
    if not lines:raise ValueError('DWD CSV empty')
    delimiter=';' if lines[0].count(';')>=lines[0].count(',') else ','
    reader=csv.DictReader(io.StringIO('\n'.join(lines)),delimiter=delimiter)
    if not reader.fieldnames:raise ValueError('DWD CSV has no columns')
    headers={norm(k):k for k in reader.fieldnames if k}
    if expect and not expect.issubset(headers):raise ValueError(f'Unexpected SWSMOS columns {list(headers)}')
    return headers,reader

def read_catalog(blob):
    headers,reader=records(blob)
    def col(names):
        return next((headers[norm(n)] for n in names if norm(n) in headers),None)
    station=col(['ID','SWSID','STATIONSID','STATIONID','KENNUNG'])
    lat=col(['LAT','LATITUDE','GEOBREITE','GEOGRAPHISCHEBREITE','BREITE','BREITENGRAD','NORTH','Y'])
    lon=col(['LON','LONG','LONGITUDE','GEOLAENGE','GEOGRAPHISCHELAENGE','LAENGE','LAENGENGRAD','EAST','X'])
    name=col(['STATIONSNAME','STATIONNAME','STATION','NAME','BEZEICHNUNG','ORT'])
    if not all((station,lat,lon)):raise ValueError(f'SWS catalogue columns unknown: {list(headers)}')
    result={}
    for row in reader:
        try:
            identifier=str(row[station]).strip()
            latitude=float(row[lat].strip().replace(',','.'))
            longitude=float(row[lon].strip().replace(',','.'))
        except (ValueError,TypeError,AttributeError):continue
        if not (47<=latitude<=56 and 5<=longitude<=16) or not identifier:continue
        label=(row.get(name,'') or identifier).strip() if name else identifier
        result[identifier]=[identifier,label,round(latitude,5),round(longitude,5)]
    if len(result)<200:raise ValueError(f'SWS catalogue too sparse ({len(result)})')
    return result

def finite(raw,minimum,maximum):
    try:
        value=float(str(raw).strip().replace(',','.'))
        return round(value,1) if minimum<=value<=maximum else None
    except ValueError:return None

def read_forecast(blob,catalog,now):
    headers,reader=records(blob,HEADERS)
    columns={k:headers[k] for k in HEADERS}
    start=now-dt.timedelta(minutes=50)
    end=now+dt.timedelta(hours=27)
    stations=defaultdict(list)
    timestamps=set()
    for row in reader:
        ident=str(row.get(columns['ID'],'')).strip()
        if ident not in catalog:continue
        try:
            forecast_time=dt.datetime.strptime(row[columns['YYYYMMDDHHMM']].strip()[:12],'%Y%m%d%H%M').replace(tzinfo=UTC)
        except (ValueError,TypeError,AttributeError):continue
        if not start<=forecast_time<=end:continue
        rc=finite(row.get(columns['RC']),1,6)
        state=int(rc) if rc is not None and rc==int(rc) else None
        temp=finite(row.get(columns['TS']),-60,75)
        air=finite(row.get(columns['TL']),-60,75)
        if all(v is None for v in (state,temp,air)):continue
        iso=forecast_time.isoformat().replace('+00:00','Z')
        stations[ident].append((iso,temp,state,air))
        timestamps.add(iso)
    times=sorted(timestamps)
    table={v:i for i,v in enumerate(times)}
    result=[]
    for station,values in stations.items():
        ordered=sorted(values,key=lambda r:r[0])
        result.append(catalog[station]+[[table[t],ts,rc,tl] for t,ts,rc,tl in ordered])
    result.sort(key=lambda x:x[0])
    if len(result)<200 or not times:raise ValueError(f'SWS run has too few valid forecasts: {len(result)} stations')
    return times,result

def build(catalog_blob, forecast_blob, run, now):
    stations=read_catalog(catalog_blob)
    times,rows=read_forecast(forecast_blob,stations,now)
    if now-run>dt.timedelta(hours=8) or run>now+dt.timedelta(minutes=30):raise ValueError('SWSMOS cycle not fresh')
    return dict(schema=1,source='DWD SWSMOS',run=run.isoformat().replace('+00:00','Z'),
                generated=now.isoformat().replace('+00:00','Z'),times=times,stations=rows)

def main():
    listing=fetch('').decode('utf-8',errors='replace')
    matches=sorted(set(re.findall(r'swsmos_(\d{14})_opendata\.csv\.bz2',listing)))
    if not matches:raise RuntimeError('No SWSMOS forecast in index')
    name='swsmos_'+matches[-1]+'_opendata.csv.bz2'
    run=dt.datetime.strptime(matches[-1],'%Y%m%d%H%M%S').replace(tzinfo=UTC)
    now=dt.datetime.now(UTC)
    output=build(fetch('swsKatalog.csv.bz2'),fetch(name),run,now)
    target=Path('data/road-weather.json')
    temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps(output,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    temp.replace(target)
    print(f'SWSMOS run {run}: {len(output["stations"])} stations / {len(output["times"])} hours, {target.stat().st_size} bytes')

if __name__=='__main__':main()
