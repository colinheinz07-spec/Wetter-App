"""Write the compressed snapshot and its small version manifest together."""
import gzip
import json
import runpy
import shutil
import sys
from pathlib import Path

audit=runpy.run_path(str(Path(__file__).with_name('audit-models.py')))['audit']

for name in sys.argv[1:]:
    base=Path('data')/name
    source=base.with_suffix('.json')
    compressed=Path(str(source)+'.gz')
    if source.exists():
        with source.open('rb') as f:
            payload=json.load(f)
        for run in payload.get('runs',[payload]):audit(run)
        temp=compressed.with_suffix('.tmp')
        with source.open('rb') as f,temp.open('wb') as raw:
            with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0,compresslevel=6) as z:
                shutil.copyfileobj(f,z)
        temp.replace(compressed)
    else:
        with gzip.open(compressed,'rt') as f:payload=json.load(f)
        for run in payload.get('runs',[payload]):audit(run)
    latest=payload['runs'][0] if 'runs' in payload else payload
    manifest={key:latest[key] for key in ('model','run','generated')}
    manifest['maxHour']=latest['hours'][-1]
    base.with_suffix('.meta.json').write_text(json.dumps(manifest,separators=(',',':')))
