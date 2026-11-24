"""Keep rolling weather payloads within the existing publication budget."""
import argparse
from pathlib import Path


def check_size(root,limit=1_500_000_000):
    root=Path(root)
    files=sorted({*root.glob('*.json'),*root.glob('*.json.gz')})
    size=sum(p.stat().st_size for p in files)
    points=sum(p.stat().st_size for p in files if p.name.startswith('point-'))
    print(f'Native snapshot: {len(files)} files, {size:,} bytes; location tiles {points:,}; limit {limit:,}',flush=True)
    if size>=limit:
        raise ValueError(f'Native payload {size:,} bytes exceeds the {limit:,}-byte budget')
    return size


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('root')
    args=parser.parse_args()
    check_size(args.root)
