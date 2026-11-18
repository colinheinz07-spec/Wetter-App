"""Fixture checks for the DWD SWSMOS compact converter (no external network)."""
import bz2
import datetime as dt
from importlib.machinery import SourceFileLoader

module=SourceFileLoader('road_ingest','scripts/ingest-road-weather.py').load_module()
now=dt.datetime(2026,11,18,12,tzinfo=dt.timezone.utc)
catalog="ID;Name;Latitude;Longitude\n" + "\n".join(f"{i};Teststation {i};50.5;7.8" for i in range(1,301))+"\n"
forecast="ID;YYYYMMDDHHmm;TL;TLSTA;RRL1c;RRS1c;RR6;WWL6;WWS3;RRS3c;R650;RC;TS;TD\n"
for i in range(1,301):
    forecast+=f"{i};202611181300;0.5;0;0;0;0;0;0;0;0;5;-0.8;-1\n"
    forecast+=f"{i};202611181400;-1;0;0;0;0;0;0;0;0;1;-2.5;-2\n"
    forecast+=f"{i};202611190100;30;0;0;0;0;0;0;0;0;6;99;-2\n" # invalid TS
d=module.build(bz2.compress(catalog.encode()),bz2.compress(forecast.encode()),now-dt.timedelta(hours=1),now)
assert d['schema']==1 and len(d['stations'])==300 and len(d['times'])==3
assert d['stations'][0][4][0]==[0,-0.8,5,0.5]
assert d['stations'][0][4][-1][1] is None
try:
    module.build(bz2.compress(catalog.encode()),bz2.compress(forecast.encode()),now-dt.timedelta(hours=12),now)
except ValueError:
    pass
else:
    raise AssertionError('Stale road-weather model accepted')
print('DWD road-weather import and stale-run protections: OK')
