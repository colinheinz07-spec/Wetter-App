// Test the actual browser data contract and selection functions without a DOM.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('index.html','utf8');
const chunk = (from,to) => html.slice(html.indexOf(from),html.indexOf(to));
const context = vm.createContext({console,Date,atob,Int16Array,Map,Set,Math,Number});
vm.runInContext(chunk('const realModelFiles=','async function fetchRealModel') + chunk('const localFormat=','const realPoint=')+
  chunk('const realPoint=','const realWeatherIcon'),context);
const d2=JSON.parse(fs.readFileSync('data/icon-d2.json','utf8'));
const eu=JSON.parse(fs.readFileSync('data/icon-eu.json','utf8'));
const run=d2.run, point=[7.8,50.5];
const packed=val=>{const b=Buffer.alloc(8);for(let i=0;i<4;i++)b.writeInt16LE(val,i*2);return b.toString('base64')};
const hours=Array.from({length:41},(_,i)=>i*6);
const ifs={schema:1,model:'IFS',run,generated:run,hours,grid:{west:7,south:50,step:1,nx:2,ny:2,scale:.1,missing:-32768},frames:Object.fromEntries(hours.map(h=>[h,{temp2:packed(100),dew:packed(50),wind:packed(150),slp:packed(10100),cloud:packed(750),rainTotal:packed(h*2),t850:packed(-30)}]))};
Object.assign(context,{d2,eu,ifs,point,run});
vm.runInContext(`for(const d of [d2,eu,ifs])realModelCache.set(d.model,validateRealData(d,d.model));`,context);
assert.equal(vm.runInContext(`realModelValue(ifs,{id:'temp2'},...point,6)`,context),10);
assert.ok(Math.abs(vm.runInContext(`realModelValue(ifs,{id:'rainrate'},...point,6)`,context)-.2)<1e-8);
assert.ok(Number.isNaN(vm.runInContext(`realModelValue(ifs,{id:'temp2'},0,0,6)`,context)));
assert.equal(vm.runInContext(`chooseLocationModel(Date.parse(run)+180*3600000,point).d.model`,context),'IFS');
const frames=vm.runInContext(`modelLocationFrames(point,Date.parse(run))`,context);
assert.ok(frames.some(f=>f.d.model==='ICON-D2'));
assert.ok(frames.some(f=>f.d.model==='ICON-EU'));
assert.ok(frames.some(f=>f.d.model==='IFS'));
assert.ok(frames.every((f,i)=>i===0||f.time>frames[i-1].time));
assert.ok(frames.at(-1).time>=Date.parse(run)+168*3600000);
assert.equal(vm.runInContext(`parameterAt('t850',point,Date.parse(run)+180*3600000,null).value`,context),-3);
assert.equal(vm.runInContext(`JSON.stringify([7.4,7.5,-1.5,-.4,0,NaN].map(temperatureText))`,context),'["7","8","-2","0","0","—"]');
Object.assign(context,{packed});
vm.runInContext(`const wwTest={...ifs,model:'ICON-D2',frames:{6:{...ifs.frames[6],ww:packed(73)},12:{...ifs.frames[12],ww:packed(95)}}};const sample=(d,hour)=>({d,hour,time:Date.parse(run)+hour*3600000,point});`,context);
assert.equal(vm.runInContext(`frameWeather(sample(wwTest,6),true).icon`,context),'21_schnee_2');
assert.equal(vm.runInContext(`frameWeather(sample(wwTest,12),true).icon`,context),'35_gewitterregen');
assert.equal(vm.runInContext(`dailyWeatherFrame([sample(wwTest,6),sample(wwTest,12)]).hour`,context),12);
vm.runInContext(`weatherCodesCache.set('ICON-D2',{run,grid:wwTest.grid,frames:{18:packed(48)}});`,context);
assert.equal(vm.runInContext(`frameWeather(sample(wwTest,18),true).icon`,context),'66_gefrierender_nebel');
assert.ok(Number.isNaN(vm.runInContext(`frameVal(sample({...wwTest,run:new Date(Date.parse(run)+3600000).toISOString()},18),'ww')`,context)));
vm.runInContext(`ifs.frames[6].ptype=packed(7);ifs.scales={ptype:1};realDecoded.delete('IFS/'+run+'/6/ptype')`,context);
assert.equal(vm.runInContext(`frameWeather(sample(ifs,6),true).icon`,context),'29_schneeregen_2');
assert.equal(vm.runInContext(`frameWeather(sample(ifs,12),true).source`,context),'Modell-Niederschlagssumme');
vm.runInContext(`const gfs={...ifs,model:'GFS',frames:{...ifs.frames,6:{...ifs.frames[6],u850:packed(30),v850:packed(40)}}};realModelCache.set('GFS',validateRealData(gfs,'GFS'));`,context);
assert.equal(vm.runInContext(`realModelValue(gfs,{id:'windp850'},...point,6)`,context),5);
assert.equal(vm.runInContext(`chooseLocationModel(Date.parse(run)+180*3600000,point).d.model`,context),'IFS');
assert.equal(vm.runInContext(`realModelCache.delete('IFS');chooseLocationModel(Date.parse(run)+180*3600000,point).d.model`,context),'GFS');
vm.runInContext(`realModelCache.set('IFS',ifs);realModelCache.delete('GFS')`,context);
console.log('GFS fallback and pressure-level wind vector: OK');
vm.runInContext(`const aifs={...ifs,model:'AIFS',hours:Array.from({length:61},(_,i)=>i*6),frames:Object.fromEntries(Array.from({length:61},(_,i)=>[i*6,{...ifs.frames[0],rainTotal:packed(i*12)}]))};const aiControl={...aifs,model:'AIFS-ENS Control'};realModelCache.set('AIFS',validateRealData(aifs,'AIFS'));realModelCache.set('AIFS-ENS Control',validateRealData(aiControl,'AIFS-ENS Control'));`,context);
assert.equal(vm.runInContext(`chooseLocationModel(Date.parse(run)+300*3600000,point).d.model`,context),'AIFS');
assert.equal(vm.runInContext(`chooseLocationModel(Date.parse(run)+300*3600000,point,false,['AIFS-ENS Control']).d.model`,context),'AIFS-ENS Control');
assert.throws(()=>vm.runInContext(`validateRealData({...aifs,frames:{...aifs.frames,6:{...aifs.frames[6],gust:'bad'}}},'AIFS')`,context),/Ungültiges Modellfeld/);
vm.runInContext(`realModelCache.delete('AIFS');realModelCache.delete('AIFS-ENS Control');const indexFixture={...ifs,model:'index-test',frames:{6:{...ifs.frames[6],t850:packed(50),rh850:packed(1000),t700:packed(-50),rh700:packed(1000),t500:packed(-200)}}};`,context);
assert.ok(Math.abs(vm.runInContext(`realModelValue(indexFixture,{id:'tt'},...point,6)`,context)-50)<1e-6);
assert.ok(Math.abs(vm.runInContext(`realModelValue(indexFixture,{id:'ki'},...point,6)`,context)-30)<1e-6);
assert.ok(Number.isNaN(vm.runInContext(`realModelValue(ifs,{id:'tt'},...point,6)`,context)));
console.log('AIFS and ENS control, extended lead times, optional field integrity and derived indices: OK');
vm.runInContext(chunk('function pressureExtrema(','// Plot exactly one pixel'),context);
assert.equal(vm.runInContext(`pressureExtrema(Array.from({length:25},(_,i)=>1000-Math.hypot(i%5-2,Math.floor(i/5)-2)*2),{nx:5,ny:5},1)[0].label`,context),'H');
console.log('Whole-degree temperatures, exact WW, IFS precipitation type and same-run supplemental fields: OK');
console.log('Existing ICON grids, IFS schema, model transitions, precipitation and missing fields: OK');
vm.runInContext(`const midnight=utcDayStart(Date.parse(run)),hourlyRun=new Date(midnight).toISOString(),nativeHours=Array.from({length:49},(_,i)=>i),native={...ifs,model:'ICON-D2',run:hourlyRun,generated:hourlyRun,hours:nativeHours,frames:Object.fromEntries(nativeHours.map(h=>[h,{...ifs.frames[0],temp2:packed(h*10),rainTotal:packed(h*2),ww:packed(61)}]))};hourlyModelCache.set('ICON-D2',[validateRealData(native,'ICON-D2')]);`,context);
assert.equal(vm.runInContext(`forecastDay(point,midnight,midnight).periods[0].mean`,context),3);
// A cloud-only WW code cannot override a positive accumulated precipitation total.
vm.runInContext(`const cloudy={...native,run:hourlyRun,frames:{...native.frames,6:{...native.frames[6],ww:packed(3)}}};const cloudyFrame=sample(cloudy,6);cloudyFrame.time=midnight+6*HOUR_MS;const interval=(frame,amount,hours=6)=>({frame,amount,hours,start:frame.time-hours*HOUR_MS,end:frame.time});`,context);
assert.equal(vm.runInContext(`forecastIcon([interval(cloudyFrame,3.7)],3.7,6,100).icon`,context),'12_regen_2');
assert.equal(vm.runInContext(`forecastIcon([interval(cloudyFrame,8)],8,6,100).icon`,context),'13_regen_3');
assert.equal(vm.runInContext(`forecastIcon([interval(cloudyFrame,20)],20,24,100).icon`,context),'14_regen_4');
assert.equal(vm.runInContext(`forecastIcon([interval(cloudyFrame,0)],0,6,100).icon`,context),'06_bedeckt');
assert.equal(vm.runInContext(`forecastIcon([interval(sample(wwTest,6),5)],5,6,100).icon`,context),'22_schnee_3');
assert.equal(vm.runInContext(`forecastIcon([interval(sample(wwTest,12),1)],1,6,100).icon`,context),'35_gewitterregen');
assert.equal(vm.runInContext(`warningLevel(25,shortRainLimits[1])`,context),2);
assert.equal(vm.runInContext(`warningLevel(90,shortRainLimits[1])`,context),4);
assert.equal(vm.runInContext(`warningLevel(90.1,shortRainLimits[1])`,context),5);
assert.equal(vm.runInContext(`localWarnings([{intervals:[interval(cloudyFrame,40)]}],midnight,300).find(w=>w.type==='Starkregen').level`,context),2);
assert.ok(vm.runInContext(`!localWarnings([{intervals:[interval(cloudyFrame,40)]}],midnight,300).some(w=>w.type==='Starkregen'&&w.period===1)`,context));
assert.ok(vm.runInContext(`!localWarnings([{intervals:[interval(sample(wwTest,6),80)]}],Date.parse(run),300).some(w=>w.type==='Starkregen')`,context));
assert.ok(vm.runInContext(`!localWarnings([{intervals:[interval(cloudyFrame,40)]}],midnight+6*HOUR_MS,300).some(w=>w.type==='Starkregen')`,context));
console.log('Summary icons use same accumulated precipitation; warning thresholds and exact valid intervals: OK');
assert.equal(vm.runInContext(`currentGridFrame(point,midnight+5.5*HOUR_MS).time`,context),vm.runInContext(`midnight+5*HOUR_MS`,context));
assert.equal(vm.runInContext(`frameVal(currentGridFrame(point,midnight+5.5*HOUR_MS),'temp2')`,context),5);
const radarBytes=Buffer.alloc(8);[0,25,-32768,100].forEach((v,i)=>radarBytes.writeInt16LE(v,2*i));
Object.assign(context,{radarPacket:{schema:1,product:'RY',time:run,intervalMinutes:5,grid:{west:7,south:50,step:1,nx:2,ny:2,scale:.01,missing:-32768},amount:radarBytes.toString('base64')}});
vm.runInContext(`const radarTest=decodeRadarPoints(radarPacket),radarNow=Date.parse(run)+60000`,context);
assert.equal(vm.runInContext(`radarGridAt(radarTest,[7,50],radarNow).rate`,context),0);
assert.equal(vm.runInContext(`radarGridAt(radarTest,[8,50],radarNow).rate`,context),3);
assert.equal(vm.runInContext(`radarGridAt(radarTest,[7,51],radarNow)`,context),null);
assert.equal(vm.runInContext(`radarGridAt(radarTest,[9,50],radarNow)`,context),null);
assert.equal(vm.runInContext(`radarGridAt(radarTest,[8,50],radarNow+21*60000)`,context),null);
console.log('Current grid never uses future hours; radar distinguishes dry, wet, missing and stale cells: OK');
// Isolate the fixture from the real, newer ICON-D2 cycle.
vm.runInContext(`realModelCache.delete('ICON-D2')`,context);
assert.ok(Math.abs(vm.runInContext(`forecastDay(point,midnight,midnight).rain`,context)-4.8)<1e-8);
assert.ok(vm.runInContext(`const day=forecastDay(point,midnight,midnight),h24=hourlyForecast([day],midnight);Math.abs(h24.reduce((s,h)=>s+h.rain,0)-day.rain)<1e-8 && h24.every(h=>h.step===1 && h.frame)`,context));
// The radar predicts a rain band much wetter than the hourly model (0.2 mm).
// Both the six-hour and daily summaries must use the exact same revised hours.
vm.runInContext(`radarNowcastData=decodeRadarNowcast({schema:1,product:'RV',time:new Date(midnight).toISOString(),intervalMinutes:5,grid:{west:7,south:50,step:1,nx:2,ny:2,scale:.01,missing:-32768},frames:Object.fromEntries(Array.from({length:24},(_,i)=>[(i+1)*5,packed(20)]))});const rvDay=forecastDay(point,midnight,midnight),rvHours=hourlyForecast([rvDay],midnight);`,context);
assert.ok(vm.runInContext(`Math.abs(rvHours[0].rain-2.4)<1e-8&&Math.abs(rvHours[1].rain-2.4)<1e-8&&Math.abs(rvHours[2].rain-.2)<1e-8`,context));
assert.ok(vm.runInContext(`Math.abs(rvDay.periods[0].rain-5.6)<1e-8&&Math.abs(rvDay.rain-rvHours.reduce((sum,h)=>sum+h.rain,0))<1e-8&&Math.abs(hourlyRainWindow(rvHours,midnight,midnight+2*HOUR_MS)-4.8)<1e-8`,context));
assert.ok(vm.runInContext(`localPrecipitationHour(point,midnight,midnight+26*60000).radarUsed===false`,context));
assert.ok(vm.runInContext(`const midHour=midnight+20*60000,mixedHour=localPrecipitationHour(point,midnight,midHour);Math.abs(mixedHour.rain-(.2/3+1.6))<1e-8&&Math.abs(hourlyRainWindow([mixedHour],midHour,midnight+HOUR_MS)-1.6)<1e-8`,context));
assert.ok(vm.runInContext(`radarNowcastData.frames[5]=packed(-32768);Math.abs(localPrecipitationHour(point,midnight,midnight).rain-(2.2+.2/12))<1e-8`,context));
vm.runInContext(`radarNowcastData=null`,context);
console.log('RV nowcast hourly and six-hour/day sums, partial hour, stale/missing radar fallback: OK');
assert.equal(vm.runInContext(`intervalLabel(midnight+18*HOUR_MS,midnight+DAY_MS)`,context),'18–00');
assert.equal(vm.runInContext(`localIntervalLabel(Date.UTC(2026,10,16,5),Date.UTC(2026,10,16,6))`,context),'06:00–07:00');
assert.ok(vm.runInContext(`const short={...ifs,run:new Date(Date.parse(run)+6*HOUR_MS).toISOString(),hours:ifs.hours.slice(0,16)};shortModelCache.set('IFS',short);modelRuns('IFS')[0]===short && chooseLocationModel(Date.parse(run)+12*HOUR_MS,point,false,['IFS']).d===short && chooseLocationModel(Date.parse(run)+168*HOUR_MS,point,false,['IFS']).d===ifs`,context));
vm.runInContext(`shortModelCache.clear()`,context);
assert.ok(vm.runInContext(`hourlyModelCache.clear();const coarseDay=forecastDay(point,utcDayStart(Date.parse(run)+120*HOUR_MS),Date.parse(run));hourlyForecast([coarseDay],coarseDay.start).every(h=>Number.isNaN(h.rain))`,context));
console.log('UTC periods, time-weighted temperature, native hourly and six-hour/daily sums: OK');
vm.runInContext(`realModelCache.set('ICON-D2',d2)`,context);
// A day starts at local midnight, not 00 UTC. Test both DST transitions.
assert.equal(vm.runInContext(`new Date(localBoundary(Date.UTC(2026,10,16,22,45))).toISOString()`,context),'2026-11-15T23:00:00.000Z');
assert.equal(vm.runInContext(`new Date(localBoundary(Date.UTC(2026,10,16,23,15))).toISOString()`,context),'2026-11-16T23:00:00.000Z');
assert.equal(vm.runInContext(`(dailyBoundaries(Date.UTC(2026,2,29,12),0)[4]-dailyBoundaries(Date.UTC(2026,2,29,12),0)[0])/HOUR_MS`,context),23);
assert.equal(vm.runInContext(`(dailyBoundaries(Date.UTC(2026,9,25,12),0)[4]-dailyBoundaries(Date.UTC(2026,9,25,12),0)[0])/HOUR_MS`,context),25);
vm.runInContext(`const savedModels=new Map(realModelCache);realModelCache.clear();hourlyModelCache.clear();const nightStart=Date.UTC(2026,10,16,10),localBounds=dailyBoundaries(nightStart,0),nightRun=new Date(localBounds[0]-6*HOUR_MS).toISOString(),nightHours=Array.from({length:49},(_,i)=>i),nightValues=[2,1,0,-1,-3,-4,1,3,5,7,9,10,11,12,13,14,14,13,11,9,7,5,4,3];const nightFixture={...native,run:nightRun,generated:nightRun,hours:nightHours,frames:Object.fromEntries(nightHours.map(h=>[h,{...native.frames[0],temp2:packed(10*(nightValues[h-6]??2)),rainTotal:packed(h*2),cloud:packed(0),ww:packed(0)}]))};hourlyModelCache.set('ICON-D2',[nightFixture]);const nightDay=forecastCalendarDays(point,nightStart)[0];`,context);
assert.equal(vm.runInContext(`nightDay.periods[0].lo`,context),-4);
assert.equal(vm.runInContext(`nightDay.hi`,context),14);
assert.equal(vm.runInContext(`nightDay.periods[0].weather.icon`,context),'12_regen_2');
assert.ok(vm.runInContext(`Math.abs(nightDay.rain-4.8)<1e-8&&!nightDay.rainEstimated`,context));
assert.equal(vm.runInContext(`forecastIcon([],0,6,0,true).icon`,context),'07_klare_nacht');
assert.equal(vm.runInContext(`forecastIcon([],0,6,100,true).icon`,context),'10_nachts_bedeckt');
// A run-wide minimum from earlier in the day must not pollute this night.
vm.runInContext(`const runningExtrema={...nightFixture,extremaWindowHours:6,frames:Object.fromEntries(nightHours.map(h=>[h,{...nightFixture.frames[h],tmin:packed(-100),tmax:packed(150)}]))};hourlyModelCache.set('ICON-D2',[runningExtrema]);`,context);
assert.equal(vm.runInContext(`forecastPeriod(point,localBounds[0]+HOUR_MS,nightStart,localBounds[1]).lo`,context),-4);
vm.runInContext(`runningExtrema.frames[12].tmin=packed(-110);realDecoded.clear()`,context);
assert.equal(vm.runInContext(`forecastPeriod(point,localBounds[0]+HOUR_MS,nightStart,localBounds[1]).lo`,context),-11);
vm.runInContext(`realDecoded.clear()`,context);
vm.runInContext(`hourlyModelCache.clear();const coarseRun=new Date(localBounds[0]-5*HOUR_MS).toISOString(),coarseFixture={...native,run:coarseRun,generated:coarseRun,hours:Array.from({length:9},(_,i)=>i*6),frames:Object.fromEntries(Array.from({length:9},(_,i)=>[i*6,{...native.frames[0],temp2:packed(i*60),rainTotal:packed(i*60)}]))};realModelCache.set('ICON-D2',coarseFixture);const coarsePeriod=forecastPeriod(point,localBounds[0],nightStart,localBounds[1]);`,context);
assert.ok(Math.abs(vm.runInContext(`coarsePeriod.mean`,context)-8)<1e-8);
assert.equal(vm.runInContext(`coarsePeriod.rainEstimated`,context),true);
assert.ok(Math.abs(vm.runInContext(`coarsePeriod.rain`,context)-6)<1e-8);
assert.ok(vm.runInContext(`const coarseHours=hourlyForecast([{periods:[coarsePeriod]}],localBounds[0]);coarseHours.slice(0,6).every(h=>Number.isFinite(frameVal(h.frame,'temp2'))&&Number.isNaN(h.rain))`,context));
vm.runInContext(`const freshRun=new Date(Date.parse(nightRun)+12*HOUR_MS).toISOString(),fresh={...coarseFixture,run:freshRun,generated:freshRun};realModelCache.set('ICON-D2',fresh);hourlyModelCache.set('ICON-D2',[nightFixture]);`,context);
assert.equal(vm.runInContext(`forecastCandidates(localBounds[2],localBounds[3],nightStart)[0].run`,context),vm.runInContext(`freshRun`,context));
assert.equal(vm.runInContext(`forecastCandidates(localBounds[0],localBounds[1],nightStart)[0].run`,context),vm.runInContext(`nightRun`,context));
// Freilingen regression: an older hourly run cannot override a newer cycle,
// and the original temperature cell overrides the coarsened map cell only
// for the identical model initialization and valid time.
vm.runInContext(`const recentRun=new Date(Date.parse(nightRun)+9*HOUR_MS).toISOString(),recent={...coarseFixture,run:recentRun,generated:recentRun};realModelCache.set('ICON-D2',recent);`,context);
assert.equal(vm.runInContext(`forecastCandidates(localBounds[2],localBounds[3],nightStart)[0].run`,context),vm.runInContext(`recentRun`,context));
const locPacked=vals=>{const bytes=Buffer.alloc(vals.length*2);vals.forEach((v,i)=>bytes.writeInt16LE(v,i*2));return bytes.toString('base64')};
Object.assign(context,{locPacked});
vm.runInContext(`const freilingen=[7.8347,50.5592],tileRun=nightRun,tileMeta={run:tileRun,generated:tileRun,tileSize:2,grid:{west:7.82,south:50.54,dx:.02,dy:.02,nx:2,ny:2}};nativeTemperatureMeta=tileMeta;nativeTemperatureTiles.set('0-0',{run:tileRun,generated:tileRun,frames:Object.fromEntries(nightHours.map(h=>[h,{temp2:locPacked([60,60,60,h===24?29:60]),tmin:locPacked([60,60,60,23])}]))});const testF={d:nightFixture,point:freilingen,hour:24};`,context);
assert.ok(Math.abs(vm.runInContext(`frameVal(testF,'temp2')`,context)-2.9)<1e-8);
assert.ok(Math.abs(vm.runInContext(`frameVal(testF,'tmin')`,context)-2.3)<1e-8);
assert.equal(vm.runInContext(`nativeTemperatureValue({...nightFixture,run:recentRun},freilingen,24,'temp2')`,context),null);
assert.equal(vm.runInContext(`nativeTemperatureCell(freilingen).n`,context),3);
assert.ok(vm.runInContext(`Number.isNaN(frameVal(testF,'tmax'))`,context));
assert.equal(vm.runInContext(`periodTemperature({lo:3,mean:6},0)`,context),3);
assert.equal(vm.runInContext(`periodTemperature({lo:3,mean:6},1)`,context),6);
vm.runInContext(`nativeTemperatureMeta=null;nativeTemperatureTiles.clear()`,context);
console.log('Freilingen regression: exact original cell, run isolation and night minimum: OK');
vm.runInContext(`realModelCache.clear();for(const [m,d] of savedModels)realModelCache.set(m,d);hourlyModelCache.clear()`,context);
console.log('Local midnight, DST, true nocturnal minima, dry night icons and coarse temperature interpolation: OK');
if(fs.existsSync('data/ifs.json')){
 const actual=JSON.parse(fs.readFileSync('data/ifs.json','utf8'));
 Object.assign(context,{actual,now:Date.parse(actual.generated),berlin:[13.4,52.52]});
 vm.runInContext('realModelCache.set("IFS",validateRealData(actual,"IFS"));realDecoded.clear()',context);
 const days=vm.runInContext(`const rows=modelLocationFrames(berlin,now,true);Array.from({length:7},(_,i)=>rows.filter(f=>localDay(f.time)===localDay(now+i*86400000)).map(f=>f.d.model))`,context);
 assert.ok(days.every(d=>d.length),JSON.stringify(days));assert.ok(days[6].includes('IFS'));
 assert.ok(vm.runInContext(`rows.every(f=>!!frameWeather(f).icon)`,context));
 // Real, published model data: no missing hour temperatures across midnight,
 // and every period minimum/maximum contains all its sampled temperatures.
 const zlib=require('node:zlib');
 for(const [model,file] of [['ICON-D2','icon-d2'],['ICON-EU','icon-eu']]){
  const path=`data/${file}-hourly.json.gz`;if(!fs.existsSync(path))continue;
  const packet=JSON.parse(zlib.gunzipSync(fs.readFileSync(path)));Object.assign(context,{model,packet});
  vm.runInContext(`hourlyModelCache.set(model,packet.runs.map(d=>validateRealData(d,model)))`,context);
 }
 for(const [name,p] of [['Berlin',[13.4,52.52]],['Westerwald',[7.8,50.5]],['München',[11.58,48.14]]]){
  Object.assign(context,{testPoint:p});
  const report=vm.runInContext(`(()=>{const days=forecastCalendarDays(testPoint,now),hours=hourlyForecast(days,now);return {days:days.map(d=>({day:localDay(d.start),lo:d.lo,hi:d.hi,models:d.periods.map(p=>p.model)})),hourCount:hours.filter(h=>Number.isFinite(frameVal(h.frame,'temp2'))).length,correct:days.every(d=>d.periods.every(p=>!p.rows.length||p.rows.every(f=>frameVal(f,'temp2')>=p.lo-1e-8&&frameVal(f,'temp2')<=p.hi+1e-8)))}})()`,context);
  assert.equal(report.hourCount,24,`${name}: ${JSON.stringify(report)}`);
  assert.ok(report.correct&&report.days.every(d=>Number.isFinite(d.lo)&&Number.isFinite(d.hi)&&d.lo<=d.hi),`${name}: ${JSON.stringify(report)}`);
  console.log(`${name}: 24 hourly temperatures and all 7 local-day extrema verified against model samples`);
 }
 console.log('Real published IFS + ICON: seven days including late-evening Today: OK');
}

 // Original-grid values remain distinct even when the old map used one coarse cell.
 assert.equal(vm.runInContext(`nativeMapTemperatureValue({meta:{grid:{west:7.8,south:50.5,dx:.02,dy:.02,nx:2,ny:2,scale:.1,missing:-32768}},values:new Int16Array([30,60,90,-32768])},7.82,50.5)`,context),6);
 assert.equal(vm.runInContext(`nativeMapTemperatureValue({meta:{grid:{west:7.8,south:50.5,dx:.02,dy:.02,nx:2,ny:2,scale:.1,missing:-32768}},values:new Int16Array([30,60,90,-32768])},7.8,50.5)`,context),3);
 assert.ok(Number.isNaN(vm.runInContext(`nativeMapTemperatureValue(null,7.8,50.5)`,context)));
 console.log('Original temperature map cells: exact, distinct, no missing-data substitution');

const mapKeys=['temp2','dew','wind','slp','cloud','rainTotal','mlcape','u850','v850'];
const fullNativeMap={schema:2,model:'ICON-D2',run,generated:run,grid:{west:7.8,south:50.5,step:.02,nx:2,ny:2,scale:.1,missing:-32768},hours:[0,3],frames:{0:mapKeys,3:mapKeys},scales:Object.fromEntries(mapKeys.map(k=>[k,k==='mlcape'?1:.1]))};
Object.assign(context,{fullNativeMap});
vm.runInContext(`const nm=validateNativeMapManifest(fullNativeMap,'ICON-D2','icon-d2');nm.decoded.set('3/mlcape',new Int16Array([50,700,1100,-32768]));nm.decoded.set('0/rainTotal',new Int16Array([2,5,12,0]));nm.decoded.set('3/rainTotal',new Int16Array([12,45,32,0]));nm.decoded.set('3/u850',new Int16Array([30,0,0,0]));nm.decoded.set('3/v850',new Int16Array([40,0,0,0]));`,context);
assert.equal(vm.runInContext(`realModelValue(nm,{id:'mlcape'},7.8,50.5,3)`,context),50);
assert.equal(vm.runInContext(`realModelValue(nm,{id:'mlcape'},7.82,50.5,3)`,context),700);
assert.ok(Number.isNaN(vm.runInContext(`realModelValue(nm,{id:'mlcape'},7.82,50.52,3)`,context)));
assert.equal(vm.runInContext(`realModelValue(nm,{id:'rain3',interval:3},7.82,50.5,3)`,context),4);
assert.equal(vm.runInContext(`realModelValue(nm,{id:'windp850'},7.8,50.5,3)`,context),5);
assert.ok(vm.runInContext(`nativeFieldsReady(nm,{id:'rain3',interval:3},3)&&!nativeFieldsReady(nm,{id:'rain1',interval:1},3)`,context));
assert.ok(!vm.runInContext(`nativeFieldsReady(nm,{id:'cloud'},3)`,context));
assert.throws(()=>vm.runInContext(`validateNativeMapManifest({...fullNativeMap,scales:{}},'ICON-D2','icon-d2')`,context));
console.log('Original map: CAPE, wind and precipitation preserve distinct native cells; missing fields stay missing');
