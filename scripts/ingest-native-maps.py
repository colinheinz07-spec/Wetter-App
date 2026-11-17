"""Independent, source-resolution model maps; one compressed file per field/lead.

The map snapshot is a rolling generated product, not source code or an archive.
No interpolation, downsampling or interpolation of time intervals.
"""
import argparse
import datetime as dt
import gzip
import json
import runpy
from pathlib import Path
import numpy as np

HERE=Path(__file__).parent
PRODUCTS=('icon-d2','icon-eu','ifs','ifs-short','aifs','aifs-ens-control','gfs')
CORE={'temp2','dew','wind','slp','cloud','rainTotal'}
GERMANY=(3.8,16.7,46.3,55.8)

def germany_hours(model):
    if model=='icon-d2':return list(range(49))
    if model=='icon-eu':return list(range(79))+list(range(81,121,3))
    if model=='gfs':return list(range(121))+list(range(123,385,3))
    if model=='ifs':return list(range(0,145,3))+list(range(150,361,6))
    if model=='ifs-short':return list(range(0,91,3))
    return list(range(0,361,6))

class Maps:
    def __init__(self,root,model,run,hours,points=True,core_hours=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.meta=dict(schema=2,model=model,run=run,generated=dt.datetime.now(dt.timezone.utc).isoformat(),hours=hours,frames={},scales={})
        self.core_hours=set(hours if core_hours is None else core_hours)
        self.meta['coreHours']=[h for h in hours if h in self.core_hours]
        self.points=runpy.run_path(str(HERE/'native-point.py'))['PointTiles'](self.root,model,run,self.meta['generated'],hours,extrema=6 if model.startswith('ICON-') else None) if points else None
    def add(self,grid,h,frame,scales):
        if self.meta.get('grid',grid)!=grid:raise ValueError('Changing grid')
        self.meta['grid']=grid
        if h in self.core_hours and not CORE<=frame.keys():raise ValueError(f'Incomplete core map +{h}')
        if grid['nx']*grid['ny']>2000000:raise ValueError('Unexpected grid size')
        import base64
        expected=grid['nx']*grid['ny']*2
        # Theta-e (Bolton) derived from the same native 850-hPa T/RH cell.
        if 't850' in frame and 'rh850' in frame:
            def unpack(field):
                a=np.frombuffer(base64.b64decode(frame[field],validate=True),dtype='<i2')
                return np.where(a==grid['missing'],np.nan,a*scales.get(field,grid['scale']))
            t=unpack('t850');rh=unpack('rh850')
            with np.errstate(invalid='ignore',divide='ignore',over='ignore'):
                e=6.112*np.exp(17.67*t/(t+243.5))*rh/100
                q=.622*e/(850-e)
                a=np.log(e/6.112);td=243.5*a/(17.67-a)+273.15;tk=t+273.15
                tl=1/(1/(td-56)+np.log(tk/td)/800)+56
                theta_l=tk*(1000/(850-e))**(2/7)*(tk/tl)**(.28*q)
                te=theta_l*np.exp((3036/tl-1.78)*q*(1+.448*q))
                te=np.where((rh>0)&(rh<=100)&(e<850)&(te>0)&(te<1000),te,np.nan)
            frame={**frame,'thetae':runpy.run_path(str(HERE/'ingest-icon.py'))['pack'](te,.1)}
        available=[]
        for field,packed in sorted(frame.items()):
            if not field.isalnum():raise ValueError('Invalid field name')
            raw=base64.b64decode(packed,validate=True)
            if len(raw)!=expected:raise ValueError(f'Wrong shape {field}')
            a=np.frombuffer(raw,dtype='<i2')
            if not np.any(a!=grid['missing']):
                if field in CORE:raise ValueError(f'Empty core {field}')
                continue
            scale=scales.get(field,grid['scale'])
            if field in self.meta['scales'] and self.meta['scales'][field]!=scale:raise ValueError('Changing scale')
            self.meta['scales'][field]=scale
            # Separate fields keep the mobile download proportional to the selected layer.
            packet=dict(schema=2,run=self.meta['run'],generated=self.meta['generated'],hour=h,field=field,values=packed)
            with gzip.open(self.root/f'{h}-{field}.json.gz','wt',compresslevel=5) as f:json.dump(packet,f,separators=(',',':'))
            available.append(field)
        self.meta['frames'][str(h)]=available
        if not available:raise ValueError(f'Empty map +{h}')
        if self.points:self.points.add(grid,h,{k:frame[k] for k in available},self.meta['scales'])
    def finish(self):
        if set(self.meta['frames'])!={str(h) for h in self.meta['hours']}:raise ValueError('Missing map step')
        (self.root/'index.json').write_text(json.dumps(self.meta,separators=(',',':')))
        if self.points:self.points.finish()

def ecmwf_high_index(api,run,h):
    # ECMWF 0.1 degree open-data files are split into surface and pressure.
    base=api['file_base'](run,h).replace('/0p25/','/0p1/')
    rows=[]
    for suffix in ('sfc','pl'):
        url=base+'-'+suffix
        rows.extend({**json.loads(line),'_base':url} for line in api['get'](url+'.index').splitlines() if line.strip())
    return rows

def global_grid(step,bounds=(-25,42,34,71)):
    # Exact subset of the published regular lat/lon grid.
    west,east,south,north=bounds
    x=np.arange(np.floor(west/step),np.ceil(east/step)+1)*step
    y=np.arange(np.floor(south/step),np.ceil(north/step)+1)*step
    grid=dict(west=float(x[0]),south=float(y[0]),step=step,nx=len(x),ny=len(y),scale=.1,missing=-32768)
    return x,y,grid

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',choices=PRODUCTS,required=True);p.add_argument('--output',required=True);p.add_argument('--max-steps',type=int);p.add_argument('--germany',action='store_true');p.add_argument('--previous-run');args=p.parse_args()
    model=args.model
    if model.startswith('icon-'):
        api=runpy.run_path(str(HERE/'ingest-icon.py'))
        cfg=api['MODELS'][model];hours=germany_hours(model) if args.germany else cfg['hours']
        stamp,offers=api['choose_run'](model,hours)
        core_hours=hours
        if args.germany:
            cfg['bounds']=GERMANY
            # Wind is published hourly even after the common ICON-EU cadence changes.
            if model=='icon-eu':hours=sorted(set(hours)|{h for h in range(79,121) if all((stamp,h) in offers[v] for v in ('u_10m','v_10m'))})
        if args.max_steps:hours=hours[:args.max_steps]
        cfg['hours']=hours
        run=dt.datetime.strptime(stamp,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc)
        if args.previous_run and run<=dt.datetime.fromisoformat(args.previous_run):
            print('No newer complete model run');return
        writer=Maps(args.output,cfg['name'],run.isoformat(),hours,points=not args.germany,core_hours=core_hours)
        api['model_data'](model,(stamp,offers),native=True,sink=writer.add,core_hours=core_hours)
    else:
        gfs=model=='gfs'
        api=runpy.run_path(str(HERE/('ingest-gfs.py' if gfs else 'ingest-ifs.py')))
        step=.1 if model in ('ifs','ifs-short') else .25
        x,y,grid=global_grid(step,GERMANY if args.germany else (-25,42,34,71))
        ns=api['frame'].__globals__
        ns.update(X=x,Y=y,GRID=grid,NATIVE_STEP=step)
        if gfs:
            hours=germany_hours(model) if args.germany else api['HOURS'];run=api['choose_run'](hours);name='GFS'
        else:
            product='ifs' if model=='ifs-short' else model
            ns['PRODUCT']=product
            hours=list(range(0,91,6)) if model=='ifs-short' else list(range(0,241,6)) if model=='ifs' else list(range(0,361,6))
            if args.germany:hours=germany_hours(model)
            if step==.1:
                ns['index']=lambda run,h:ecmwf_high_index(api,run,h)
            run=api['choose_run'](model=='ifs-short',hours)
            name=api['PRODUCTS'][product][3]
        if args.max_steps:hours=hours[:args.max_steps]
        if args.previous_run and run<=dt.datetime.fromisoformat(args.previous_run):
            print('No newer complete model run');return
        writer=Maps(args.output,name,run.isoformat(),hours,points=not args.germany)
        previous={}
        for h in hours:
            frame=api['frame'](run,h,previous) if gfs else api['frame'](run,h)[1]
            writer.add(grid,h,frame,api['SCALES'])
    writer.finish()
if __name__=='__main__':main()


