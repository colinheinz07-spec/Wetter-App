"""Validate published weather snapshots and report actual parameter coverage.

Missing optional parameters are reported, never synthesized or interpreted as zero.
Run: python scripts/audit-models.py
"""
import array
import base64
import collections
import datetime as dt
import gzip
import json
from pathlib import Path

CORE = {'temp2', 'dew', 'wind', 'slp', 'cloud', 'rainTotal'}


def audit(d):
    grid = d['grid']
    hours = d['hours']
    assert d['schema'] == 1 and grid['missing'] == -32768 and grid['scale'] == .1
    assert grid['nx'] > 1 and grid['ny'] > 1 and grid['step'] > 0
    assert len(hours) > 1 and hours[0] == 0 and hours[1] > 0
    assert hours == list(range(0, hours[-1] + 1, hours[1]))
    assert set(d['frames']) == {str(h) for h in hours}
    assert dt.datetime.fromisoformat(d['run']) <= dt.datetime.fromisoformat(d['generated'])
    cells = grid['nx'] * grid['ny']
    coverage = collections.Counter()
    previous = None
    for hour in hours:
        frame = d['frames'][str(hour)]
        assert CORE <= frame.keys(), (d['model'], hour, CORE - frame.keys())
        for key, encoded in frame.items():
            raw = base64.b64decode(encoded, validate=True)
            assert len(raw) == cells * 2, (d['model'], hour, key, 'invalid raster length')
            values = array.array('h', raw)
            if __import__('sys').byteorder != 'little':
                values.byteswap()
            populated = any(v != -32768 for v in values)
            if key in CORE:
                assert populated, (d['model'], hour, key, 'empty required field')
            if populated:
                coverage[key] += 1
            if key == 'rainTotal':
                assert all(v == -32768 or v >= 0 for v in values), (d['model'], hour, 'negative precipitation')
                if previous is not None:
                    # GRIB packing can introduce a few tenths of a mm of
                    # rounding jitter in independently encoded accumulations.
                    assert all(a == -32768 or b == -32768 or b >= a - 5 for a, b in zip(previous, values)), (d['model'], hour, 'decreasing cumulative precipitation')
                previous = values
            if key in ('cloud','lowcloud','midcloud','highcloud','rh2'):
                assert all(v == -32768 or 0 <= v <= 1000 for v in values), (d['model'], hour, key, 'invalid percentage')
    partial = {key: f'{coverage[key]}/{len(hours)}' for key in sorted({k for f in d['frames'].values() for k in f}) if coverage[key] != len(hours)}
    print(f"{d['model']} {d['run']} +{hours[-1]}h: {len(hours)} steps, {len(coverage)} populated fields, partial: {partial or 'none'}")
    return coverage


def main():
    root = Path('data')
    for name in ('icon-d2', 'icon-eu', 'ifs', 'ifs-short', 'gfs', 'aifs', 'aifs-ens-control', 'icon-d2-hourly', 'icon-eu-hourly'):
        path = root / (name + '.json')
        compressed = root / (name + '.json.gz')
        if not path.exists() and not compressed.exists():
            print(f'{name}: no published snapshot yet')
            continue
        with (path.open() if path.exists() else gzip.open(compressed, 'rt')) as f:
            data = json.load(f)
        for run in data.get('runs', [data]):
            audit(run)


if __name__ == '__main__':
    main()
