"""Native-grid convective diagnostics from a single model/run/lead.

Pressure-level approximations, NOT storm-resolving predictions. Bolton
theta-e pseudo-adiabatic parcels, virtual-temperature buoyancy, Bunkers
right-moving storm motion, Thompson effective inflow (100 J/kg, -250 J/kg).
SCP/STP: NWS Mesoscale Parameters; SHIP: NOAA NSHARP (44e6 variant).
WMSI: Pryor & Ellrod (2004), sampled midlevel minimum 500–700 hPa.
No horizontal/time interpolation, no invented values for incomplete profiles.
https://www.weather.gov/source/zhu/ZHU_Training_Page/convective_parameters/Sounding_Stuff/MesoscaleParameters.html
https://vlab.noaa.gov/web/oclo/nsharp-hail-and-tornado-reference
https://www.star.nesdis.noaa.gov/star/documents/bios/Pryor_K/wmsiposter05.pdf
"""
import base64
import functools
import numpy as np

LEVELS=(1000,975,950,925,900,850,800,700,600,500,400,300,250,200,150,100)
SCALES=dict(scp=.01,stp=.01,ship=.01,downburst=.1,dcape=1,
            s01=.1,s03=.1,s06=.1,srh01=1,srh03=1,
            mucape=1,mucin=1,mlcape=1,mlcin=1,cape=1,cin=1)
G=9.80665
EPS=.622

def vapor(t):
    return 6.112*np.exp(17.67*t/(t+243.5))

def mixing(p,e):
    return np.where((e>0)&(e<p),EPS*e/(p-e),np.nan)

def dewpoint(e):
    a=np.log(e/6.112)
    return 243.5*a/(17.67-a)

def lcl_temp(t,td):
    t=t+273.15;td=td+273.15
    return 1/(1/(td-56)+np.log(t/td)/800)+56

def thetae(p,t,e):
    r=mixing(p,e);tk=t+273.15;tl=lcl_temp(t,dewpoint(e))
    return tk*(1000/(p-e))**(2/7)*(tk/tl)**(.28*r)*np.exp((3036/tl-1.78)*r*(1+.448*r))

@functools.lru_cache(maxsize=1)
def moist_table():
    # Invert saturated Bolton theta-e on a small lookup table. Interpolation
    # is thermodynamic, not a fabricated finer-resolution model raster.
    p=np.arange(100.,1102.,2.)[:,None];te=np.arange(180.,501.,.5)[None,:]
    a=np.full((len(p),te.size),-115.);b=np.full_like(a,65.)
    for _ in range(19):
        mid=(a+b)/2;e=vapor(mid);value=thetae(p,mid,e)
        high=(e>=p)|(~np.isfinite(value))|(value>te)
        a=np.where(high,a,mid);b=np.where(high,mid,b)
    return ((a+b)/2).astype(np.float32)

def moist(p,te):
    pp=np.clip((np.nan_to_num(p,nan=100)-100)/2,0,499.999)
    tt=np.clip((np.nan_to_num(te,nan=180)-180)/.5,0,639.999)
    i=pp.astype(np.int32);j=tt.astype(np.int32);x=pp-i;y=tt-j;table=moist_table()
    t=(1-x)*((1-y)*table[i,j]+y*table[i,j+1])+x*((1-y)*table[i+1,j]+y*table[i+1,j+1])
    return np.where((p>=100)&(p<=1100)&(te>=180)&(te<=500),t,np.nan)

def virtual(t,r):return (t+273.15)*(1+r/EPS)/(1+r)

def at_height(z,values,target):
    result=np.full(target.shape,np.nan)
    for i in range(1,len(z)):
        a,b=z[i-1],z[i];valid=(target>=a)&(target<=b)&(b>a)
        f=np.divide(target-a,b-a,out=np.zeros_like(target),where=b>a)
        result=np.where(valid,values[i-1]+f*(values[i]-values[i-1]),result)
    return result

def pressure_at(p,values,target):
    result=np.full(target.shape,np.nan)
    for i in range(1,len(p)):
        a,b=p[i-1],p[i];valid=(target<=a)&(target>=b)&(b<a)
        f=np.divide(np.log(target/a),np.log(b/a),out=np.zeros_like(target),where=b<a)
        result=np.where(valid,values[i-1]+f*(values[i]-values[i-1]),result)
    return result

def wind_integrals(z,u,v,low,high,storm=None):
    """Clip each model segment at layer boundaries, integrating actual winds."""
    su=np.zeros_like(low);sv=su.copy();srh=su.copy()
    for i in range(1,len(z)):
        a,b=z[i-1],z[i];lo=np.maximum(low,a);hi=np.minimum(high,b);dz=np.maximum(0,hi-lo)
        f=np.divide(lo-a,b-a,out=np.zeros_like(lo),where=b>a);g=np.divide(hi-a,b-a,out=np.zeros_like(hi),where=b>a)
        ua=u[i-1]+f*(u[i]-u[i-1]);ub=u[i-1]+g*(u[i]-u[i-1]);va=v[i-1]+f*(v[i]-v[i-1]);vb=v[i-1]+g*(v[i]-v[i-1])
        su+=np.where(dz>0,(ua+ub)*.5*dz,0);sv+=np.where(dz>0,(va+vb)*.5*dz,0)
        if storm is not None:
            cu,cv=storm;srh+=np.where(dz>0,(ub-cu)*(va-cv)-(ua-cu)*(vb-cv),0)
    ok=(high>low)&(low>=0)&(high<=z[-1]);width=np.where(ok,high-low,np.nan)
    return su/width,sv/width,np.where(ok,srh,np.nan)

def positive_area(a,b,dz):
    """Piecewise linear positive buoyancy integral including zero crossing."""
    both=(a>=0)&(b>=0);cross=(a*b<0)
    fraction=np.divide(np.maximum(a,b),np.abs(b-a),out=np.zeros_like(a),where=a!=b)
    return np.where(both,.5*(a+b)*dz,np.where(cross,.5*np.maximum(a,b)*fraction*dz,0))

def parcel(p,z,t,r,envtv,start_p,start_z,start_t,start_e):
    te=thetae(start_p,start_t,start_e);tl=lcl_temp(start_t,dewpoint(start_e));pl=start_p*(tl/(start_t+273.15))**(1004/287.05)
    zl=pressure_at(p,z,pl);zl=np.where(np.isclose(pl,start_p),start_z,zl)
    pt=np.where(p>=pl,(start_t+273.15)*(p/start_p)**(287.05/1004)-273.15,moist(p,te))
    rp=np.where(p>=pl,mixing(start_p,start_e),mixing(p,vapor(pt)))
    buoy=G*(virtual(pt,rp)-envtv)/envtv
    valid=np.isfinite(zl)&np.all(np.isfinite(buoy),axis=0)
    cape=np.zeros_like(start_p);cin=cape.copy();el=np.full_like(cape,np.nan);lfc=el.copy()
    for i in range(1,len(z)):
        a,b=z[i-1],z[i];lo=np.maximum(a,start_z);dz=np.maximum(0,b-lo)
        delta=b-a;f=np.divide(lo-a,delta,out=np.zeros_like(lo),where=delta>0);ba=buoy[i-1]+f*(buoy[i]-buoy[i-1]);bb=buoy[i]
        # CIN from origin up to the first positive buoyant segment above LCL.
        lo2=np.maximum(lo,zl);g=np.divide(lo2-a,delta,out=np.zeros_like(lo2),where=delta>0)
        bc=buoy[i-1]+g*(buoy[i]-buoy[i-1]);d2=np.maximum(0,b-lo2)
        before=~np.isfinite(lfc)
        is_pos=(d2>0)&((bc>0)|(bb>0));cross=np.divide(-bc,bb-bc,out=np.zeros_like(bc),where=bb!=bc)
        entry=np.where(bc>=0,lo2,lo2+np.clip(cross,0,1)*d2)
        end=np.where(before&is_pos,entry,b)
        nd=np.maximum(0,end-lo);nf=np.divide(end-lo,dz,out=np.zeros_like(nd),where=dz>0)
        bending=ba+nf*(bb-ba)
        cin-=np.where(before,positive_area(-ba,-bending,nd),0)
        lfc=np.where(before&is_pos,entry,lfc)
        cape+=positive_area(bc,bb,d2)
        exit_cross=(d2>0)&(bc>0)&(bb<=0)
        el=np.where(exit_cross,lo2+np.clip(cross,0,1)*d2,np.where(is_pos&(bb>0),np.nan,el))
    valid &= ((cape==0)|np.isfinite(el)) & (p[-1]<=200)
    # With no free convection, CIN to an LFC does not exist. Never publish
    # the integral of negative buoyancy up to the top of the sounding.
    return np.where(valid,cape,np.nan),np.where(valid&np.isfinite(lfc),cin,np.nan),np.where(valid,el,np.nan),zl

def derive_chunk(a,levels):
    ps=a['ps'];ground=a['orog'];ts=a['temp2'];td=a['dew'];speed=a['wind']/3.6;direction=np.radians(a['winddir']);n=len(ps)
    us=-speed*np.sin(direction);vs=-speed*np.cos(direction)
    valid=(ps>=450)&(ps<=1100)&np.isfinite(ground)&(ts>=-80)&(ts<=60)&(td<=ts+.3)&(td>-110)&np.isfinite(us)&np.isfinite(vs)&(speed>=0)
    p=[ps];z=[np.zeros(n)];t=[ts];e=[vapor(np.minimum(ts,td))];u=[us];v=[vs]
    for level in levels:
        above=(level<ps-.1)
        zz=a[f'z{level}']*10-ground;tt=a[f't{level}'];rh=a[f'rh{level}'];uu=a[f'u{level}'];vv=a[f'v{level}']
        good=np.isfinite(zz)&np.isfinite(tt)&(rh>=0)&(rh<=105)&np.isfinite(uu)&np.isfinite(vv)&(zz>z[-1])&(p[-1]-level<=(160 if level>700 else 200))
        valid &= ~above|good
        # 0.0% is below the packed RH field's 0.1%-precision; use the
        # half-quantization floor solely for the logarithmic dewpoint.
        p.append(np.where(above,level,p[-1]));z.append(np.where(above,zz,z[-1]));t.append(np.where(above,tt,t[-1]));e.append(np.where(above,vapor(tt)*np.clip(rh,.05,100)/100,e[-1]));u.append(np.where(above,uu,u[-1]));v.append(np.where(above,vv,v[-1]))
    p,z,t,e,u,v=map(np.asarray,(p,z,t,e,u,v));r=mixing(p,e);envtv=virtual(t,r);te=thetae(p,t,e)
    valid &= np.all(np.isfinite(envtv)&np.isfinite(te),axis=0)&(p[-1]<=200)&(z[-1]>=6000)
    # 25-hPa low-level samples help locate the effective inflow layer; they
    # are vertical interpolations of the actual (often sparse) pressure profile.
    zeros=np.zeros(n);caps=[];cins=[];els=[];lcls=[];zs=[];tes=[];rs=[]
    for delta in (*range(0,301,25),350,400,450,500,550,600):
        pp=ps-delta
        if delta==0:zz,tt,ee=z[0],t[0],e[0]
        else:zz,tt,ee=(pressure_at(p,arr,pp) for arr in (z,t,e))
        caps_i,cins_i,el,lcl=parcel(p,z,t,r,envtv,pp,zz,tt,ee)
        caps.append(caps_i);cins.append(cins_i);els.append(el);lcls.append(lcl);zs.append(zz);tes.append(thetae(pp,tt,ee));rs.append(mixing(pp,ee))
    caps,cins,els,zs,tes,rs=map(np.asarray,(caps,cins,els,zs,tes,rs));known=np.isfinite(caps)&((caps<100)|np.isfinite(cins));all_parcels=np.all(known[:13],axis=0)
    mu_idx=np.argmax(np.where(np.isfinite(tes[:13]),tes[:13],-np.inf),axis=0);idx=np.arange(n);mu=caps[mu_idx,idx];mu_cin=cins[mu_idx,idx];mu_el=els[mu_idx,idx];mu_r=rs[mu_idx,idx]
    # 100-hPa mean of potential temperature and mixing ratio, weighted by pressure.
    mlps=ps;mltheta=[];mlr=[]
    for d in range(0,101,25):
        pp=ps-d;tt=t[0] if d==0 else pressure_at(p,t,pp);ee=e[0] if d==0 else pressure_at(p,e,pp)
        mltheta.append((tt+273.15)*(1000/pp)**(287.05/1004));mlr.append(mixing(pp,ee))
    weights=np.array([.125,.25,.25,.25,.125])[:,None];mlt=np.sum(weights*np.asarray(mltheta),axis=0)*(ps/1000)**(287.05/1004)-273.15;mix=np.sum(weights*np.asarray(mlr),axis=0);mle=ps*mix/(EPS+mix)
    # A very shallow superadiabatic surface produces a mixed-layer parcel
    # that is cooler than the air at the surface; never allow supersaturation.
    mle=np.minimum(mle,vapor(mlt));mlcape,mlcin,_,mllcl=parcel(p,z,t,r,envtv,mlps,zeros,mlt,mle)
    wind=lambda target:(at_height(z,u,target),at_height(z,v,target))
    def shear(low,high):
        ua,va=wind(low);ub,vb=wind(high);return np.hypot(ub-ua,vb-va)
    s01= shear(zeros,zeros+1000);s03=shear(zeros,zeros+3000);s06=shear(zeros,zeros+6000)
    lu,lv,_=wind_integrals(z,u,v,zeros,zeros+500);hu,hv,_=wind_integrals(z,u,v,zeros+5500,zeros+6000);mu_w,mv_w,_=wind_integrals(z,u,v,zeros,zeros+6000)
    du=hu-lu;dv=hv-lv;mag=np.hypot(du,dv);cu=mu_w+7.5*dv/np.where(mag>.1,mag,np.nan);cv=mv_w-7.5*du/np.where(mag>.1,mag,np.nan)
    srh01=wind_integrals(z,u,v,zeros,zeros+1000,(cu,cv))[2];srh03=wind_integrals(z,u,v,zeros,zeros+3000,(cu,cv))[2]
    # Contiguous first qualifying layer. If the last searched parcel is
    # eligible, the top remains unknown rather than truncating the layer.
    eligible=(caps>=100)&(cins>=-250);has=eligible.any(axis=0);first=eligible.argmax(axis=0)
    after=np.arange(len(caps))[:,None]>first;stop=after&~eligible;first_fail=stop.argmax(axis=0);closed=stop.any(axis=0)&known[first_fail,idx];last=np.maximum(first,first_fail-1)
    base=zs[first,idx];top=(zs[last,idx]+zs[first_fail,idx])/2;esrh=wind_integrals(z,u,v,base,top,(cu,cv))[2];ebwd=shear(base,base+(mu_el-base)*.5)
    effective=has&closed&(top>base)&(mu_el>top)&np.isfinite(esrh)&np.isfinite(ebwd)
    scp_term=np.where(ebwd<10,0,np.minimum(ebwd/20,1));scp=np.maximum(0,mu*esrh/(1000*50)*scp_term)
    stp_term=np.where(ebwd<12.5,0,np.minimum(ebwd/20,1.5));stp=np.where(mlcape==0,0,np.maximum(0,mlcape/1500*np.clip((2000-mllcl)/1000,0,1)*esrh/150*stp_term*np.clip((200+mlcin)/150,0,1)))
    scp=np.where(all_parcels&~has,0,np.where(effective,scp,np.nan));stp=np.where(all_parcels&~has,0,np.where(effective,np.where(base<=1,stp,0),np.nan))
    # SHIP NOAA NSHARP public equation; MU mixing ratio in g/kg.
    p700=zeros+700;p500=zeros+500;z700=pressure_at(p,z,p700);z500=pressure_at(p,z,p500);t700=pressure_at(p,t,p700);t500=pressure_at(p,t,p500)
    lapse=(t700-t500)/((z500-z700)/1000);ship=mu*(mu_r*1000)*np.maximum(0,lapse)*np.maximum(0,-t500)*s06/44000000
    # Downdraft parcel: minimum theta-e in the lowest 400 hPa; cool to
    # saturation and descend along a saturated adiabat; integrate negative
    # virtual buoyancy. No entrainment / hydrometeor loading assumed.
    dte=np.where((p<ps)&(p>=ps-400)&np.isfinite(te),te,np.inf);didx=dte.argmin(axis=0);dstart=z[didx,idx];dtheta=dte[didx,idx]
    dt=moist(p,dtheta);db=G*(virtual(dt,mixing(p,vapor(dt)))-envtv)/envtv;dcape=np.zeros(n)
    for i in range(1,len(z)):
        dz=np.maximum(0,np.minimum(z[i],dstart)-z[i-1]);dcape+=positive_area(-db[i-1],-db[i],dz)
    dcape=np.where(np.isfinite(dtheta)&(dstart>0)&(p[-1]<=ps-400)&np.all(np.isfinite(db),axis=0),dcape,np.nan)
    mid=np.where((p>=500)&(p<=700),te,np.inf).min(axis=0);wmsi=np.where(np.isfinite(mid),caps[0]*np.maximum(0,te[0]-mid)/1000,np.nan)
    result=dict(scp=scp,stp=stp,ship=ship,downburst=wmsi,dcape=dcape,dcapeSpeed=3.6*np.sqrt(2*dcape),ehi03=mlcape*srh03/160000,s01=s01,s03=s03,s06=s06,srh01=srh01,srh03=srh03,mucape=mu,mucin=mu_cin,mlcape=mlcape,mlcin=mlcin,cape=caps[0],cin=cins[0])
    return {k:np.where(valid&np.isfinite(val),val,np.nan) for k,val in result.items()}

def add_diagnostics(grid,frame,scales,chunk=16384):
    """Encode only valid new fields, preserving upstream native diagnostics."""
    base=('ps','orog','temp2','dew','wind','winddir')
    levels=[p for p in LEVELS if all(f'{k}{p}' in frame for k in ('t','rh','z','u','v'))]
    if not all(k in frame for k in base) or len(levels)<6 or levels[-1]>200:return frame,scales
    keys=[*base,*(f'{k}{p}' for p in levels for k in ('t','rh','z','u','v'))]
    raw={k:np.frombuffer(base64.b64decode(frame[k],validate=True),dtype='<i2') for k in keys};size=grid['nx']*grid['ny']
    if any(len(q)!=size for q in raw.values()):raise ValueError('Profile grid shape mismatch')
    outputs={k:np.full(size,-32768,dtype='<i2') for k in SCALES if k not in frame}
    with np.errstate(all='ignore'):
        for start in range(0,size,chunk):
            sl=slice(start,min(start+chunk,size));arrays={k:np.where(v[sl]==grid['missing'],np.nan,v[sl]*scales.get(k,grid['scale'])) for k,v in raw.items()}
            derived=derive_chunk(arrays,levels)
            for k,out in outputs.items():
                vals=np.rint(derived[k]/SCALES[k]);ok=np.isfinite(vals)&(vals>=-32767)&(vals<=32767);out[sl]=np.where(ok,vals,-32768).astype('<i2')
    new={k:base64.b64encode(v.tobytes()).decode('ascii') for k,v in outputs.items() if np.any(v!=-32768)}
    return {**frame,**new},{**scales,**{k:SCALES[k] for k in new}}
