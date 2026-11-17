// Regression tests using small, deterministic parcels and model cells.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const html=fs.readFileSync('index.html','utf8');
const js=html.split('<script>')[1].split('</script>')[0];
new vm.Script(js);
const chunk=(a,b)=>html.slice(html.indexOf(a),html.indexOf(b));
const context=vm.createContext({console,Date,atob,Int16Array,Map,Set,Math,Number});
vm.runInContext(chunk('const realModelFiles=','async function fetchRealModel')+chunk('const localFormat=','const realPoint=')+chunk('const realPoint=','const realWeatherIcon'),context);
const run='2026-11-16T00:00:00.000Z',point=[7.82,50.54];
const packed=(...values)=>{const b=Buffer.alloc(values.length*2);values.forEach((v,i)=>b.writeInt16LE(v,i*2));return b.toString('base64')};
const field=v=>packed(v,v,v,v);
const grid={west:7.8,south:50.52,step:.02,nx:2,ny:2,scale:.1,missing:-32768};
const hours=Array.from({length:49},(_,i)=>i);
const frames=Object.fromEntries(hours.map(h=>[h,{temp2:field(h===14?130:120),dew:field(80),wind:field(100),gust:field(1600),slp:field(10100),cloud:field(100),rainTotal:field(h*10),t850:field(100),rh850:field(1000),u850:field(30),v850:field(40),u500:field(150),v500:field(200),mlcape:field(10000),srh03:field(1600),dcape:field(5000),ww:field(61)}]));
const fixture={schema:1,model:'ICON-D2',run,generated:run,grid,hours,frames};Object.assign(context,{fixture,point,run,packed});
const ev=code=>vm.runInContext(code,context);
ev(`hourlyModelCache.set('ICON-D2',[validateRealData(fixture,'ICON-D2')]); const now=Date.parse(run)+12.5*HOUR_MS;`);
assert.deepEqual(Array.from(ev(`[0,1,2,3].map(i=>packedCell(packed(-32768,-3,129,32767),i))`)),[-32768,-3,129,32767]);
assert.equal(ev(`realModelValue(fixture,{id:'windp850'},...point,12)`),5);
assert.equal(ev(`realModelValue(fixture,{id:'s850500'},...point,12)`),20);
assert.ok(Math.abs(ev(`realModelValue(fixture,{id:'winddirp850'},...point,12)`)-216.86989765)<1e-6);
assert.ok(ev(`realModelValue(fixture,{id:'q850'},...point,12)`)>8);
assert.equal(ev(`realModelValue(fixture,{id:'lclApprox'},...point,12)`),500);
assert.equal(ev(`realModelValue(fixture,{id:'ehi03'},...point,12)`),1);
assert.ok(Number.isNaN(ev(`realModelValue(fixture,{id:'srh01'},...point,12)`)));
assert.equal(ev(`currentParameterAt('windp850',point,now,null).frame.time`),Date.parse(run)+12*3600000);
assert.ok(ev(`currentParameterAt('windp850',point,now,null).frame.time<=now`));
assert.ok(Number.isNaN(ev(`currentParameterAt('windp850',point,Date.parse(run)+36*HOUR_MS,null).value`)));
// Same model time and cell for derived quantities; never mix sources.
assert.ok(Number.isNaN(ev(`realModelValue({...fixture,frames:{12:{...fixture.frames[12],v500:undefined}}},{id:'s850500'},...point,12)`)));
assert.equal(ev(`mapFieldRequirements(fixture,{id:'s850500',interval:0},12).length`),4);
assert.equal(ev(`forecastPeriod(point,Date.parse(run)+12*HOUR_MS,now,Date.parse(run)+18*HOUR_MS,fixture).hi`),13);
// Native coarse snapshot must not suppress a separate hourly rainfall product.
ev(`const newerRun=new Date(Date.parse(run)+6*HOUR_MS).toISOString(),coarse={...fixture,run:newerRun,generated:newerRun,hours:[0,3,6,9,12,15,18,21,24,27,30,33,36,39,42],frames:Object.fromEntries([0,3,6,9,12,15,18,21,24,27,30,33,36,39,42].map(h=>[h,fixture.frames[h]]))};realModelCache.set('ICON-D2',coarse);const block=forecastPeriod(point,Date.parse(run)+12*HOUR_MS,now,Date.parse(run)+18*HOUR_MS,coarse);const hourRows=hourlyForecast([{periods:[block]}],now)`);
assert.equal(ev('block.step'),3);assert.equal(ev('hourRows[0].step'),1);assert.equal(ev('hourRows[0].rain'),1);
// A complete explicit model vertical profile, with a known 300 m surface.
context.profile={temp2:20,dew:14,wind:18,winddir:270,orog:300,ps:970,mlcape:500};
for(const [p,z,t,u,v] of [[950,500,18,7,0],[850,1500,10,12,2],[700,3100,-1,18,5],[600,4300,-11,22,7],[500,5700,-24,27,10],[400,7400,-39,32,13],[300,9400,-54,37,15],[250,10500,-59,42,15],[200,12000,-57,45,16]]){Object.assign(context.profile,{['z'+p]:z/10,['t'+p]:t,['rh'+p]:60,['u'+p]:u,['v'+p]:v})}
const profile=ev(`calculateExpertProfile(k=>profile[k]??NaN)`);
assert.ok(Math.abs(profile.s01-Math.hypot(6,1.6))<1e-6);assert.ok(profile.s03>profile.s01&&profile.s06>profile.s03);assert.ok(Number.isFinite(profile.srh01)&&Number.isFinite(profile.srh03)&&Number.isFinite(profile.stormrel));
assert.ok(profile.lcl>400&&profile.lcl<1200);assert.ok(Number.isFinite(profile.thetae)&&Number.isFinite(profile.freezing));
assert.ok(Number.isNaN(ev(`calculateExpertProfile(k=>k==='temp2'?15:NaN).s01??NaN`)));
// Extreme single-model output cannot by itself declare an exceptional event.
ev(`const frame={d:fixture,hour:14,time:Date.parse(run)+14*HOUR_MS,point};const storm={start:frame.time-HOUR_MS,end:frame.time,frame,hours:1,amount:1};`);
assert.equal(ev(`localWarnings([{intervals:[storm]}],now,300).find(w=>w.type==='Sturm / Orkan').level`),4);
assert.equal(ev(`localWarnings([{intervals:[storm]}],now,300).find(w=>w.type==='Sturm / Orkan').exceptionalCandidate`),true);
assert.equal(ev(`localWarnings([{intervals:[storm]}],Date.parse(run)+20*HOUR_MS,300).length`),0);
assert.ok(html.indexOf('id="model-canvas"')<html.indexOf('id="map-time-controls"'));
assert.ok(html.indexOf('id="map-time-controls"')<html.indexOf('id="map-interval"'));
for(const id of ['map-back','map-next','map-play','map-time'])assert.equal((html.match(new RegExp('id="'+id+'"','g'))||[]).length,1);
console.log('Syntax, exact signed raster cells, profile diagnostics, no future/stale current data, daily maximum, warning cap and map control placement: OK');

