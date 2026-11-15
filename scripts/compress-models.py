"""Produce deterministic gzip transport copies of the published grids."""
import gzip
import shutil
from pathlib import Path

data=Path('data')
for model in ('icon-d2','icon-eu','ifs','gfs'):
    source=data/f'{model}.json';dest=data/f'{model}.json.gz'
    if not source.exists():continue
    # Validate the existing transport corresponds to the exact source bytes.
    if dest.exists():
        try:
            with gzip.open(dest,'rb') as old,source.open('rb') as current:
                while True:
                    a,b=old.read(1024*1024),current.read(1024*1024)
                    if a!=b:break
                    if not a:break
                if a==b==b'':continue
        except (OSError,EOFError):pass
    temp=dest.with_suffix('.tmp')
    with source.open('rb') as current,temp.open('wb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',compresslevel=6,mtime=0) as compressed:
            shutil.copyfileobj(current,compressed)
    temp.replace(dest)
    print(f'{model}: {source.stat().st_size} → {dest.stat().st_size} bytes',flush=True)
