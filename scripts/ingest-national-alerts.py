"""Official DWD WFS polygons. Valid warnings, not proof of observed weather."""
import datetime as dt
import gzip
import json
import urllib.request
from pathlib import Path

URL = ('https://maps.dwd.de/geoserver/dwd/ows?service=WFS&version=2.0.0'
       '&request=GetFeature&typeNames=dwd:Warnungen_Gemeinden_vereinigt'
       '&outputFormat=application/json&srsName=EPSG:4326')

def timestamp(value):
    return int(dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())

def normalize(doc, now):
    if doc.get('type') != 'FeatureCollection' or not isinstance(doc.get('features'), list):
        raise ValueError('Invalid DWD feature collection')
    out = []
    for f in doc['features']:
        p, g = f.get('properties', {}), f.get('geometry') or {}
        if p.get('STATUS') != 'Actual' or p.get('MSGTYPE') not in ('Alert', 'Update') or p.get('SCOPE') != 'Public':
            continue
        try:
            start, end, sent = timestamp(p.get('ONSET') or p['EFFECTIVE']), timestamp(p['EXPIRES']), timestamp(p['SENT'])
        except (TypeError, ValueError, KeyError):
            continue
        if end <= now or end <= start or sent > now + 300 or start > now + 48*3600:
            continue
        polygons = g.get('coordinates') if g.get('type') == 'MultiPolygon' else [g.get('coordinates')] if g.get('type') == 'Polygon' else []
        # DWD WFS explicitly returns EPSG:4326 longitude, latitude.
        if not polygons or not all(r and len(r[0]) >= 4 and all(4 <= c[0] <= 17 and 46 <= c[1] <= 56 for c in r[0]) for r in polygons):
            continue
        sev = {'Minor':1, 'Moderate':2, 'Severe':3, 'Extreme':4}.get(p.get('SEVERITY'), 0)
        possible = p.get('CERTAINTY') in ('Possible', 'Unknown', 'Unlikely') or 'VORAB' in (p.get('HEADLINE') or '').upper()
        out.append(dict(id=p['IDENTIFIER'], start=start, end=end, sent=sent, level=sev, possible=possible,
                        certainty=p.get('CERTAINTY'), event=p.get('EVENT'), headline=p.get('HEADLINE'),
                        description=p.get('DESCRIPTION'), instruction=p.get('INSTRUCTION'), altitude=p.get('ALTITUDE'),
                        ceiling=p.get('CEILING'), polygons=polygons))
    return dict(schema=1, generated=now, source='DWD · WFS Warnungen_Gemeinden_vereinigt', alerts=out)

def main():
    req=urllib.request.Request(URL, headers={'User-Agent':'WetterApp/1.0'})
    with urllib.request.urlopen(req, timeout=35) as response:
        doc=json.load(response)
    result=normalize(doc, int(dt.datetime.now(dt.timezone.utc).timestamp()))
    path=Path('data/national-alerts.json.gz');path.parent.mkdir(exist_ok=True)
    with gzip.open(path,'wt',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,separators=(',',':'))
    print('Official warning polygons:', len(result['alerts']))

if __name__ == '__main__': main()
