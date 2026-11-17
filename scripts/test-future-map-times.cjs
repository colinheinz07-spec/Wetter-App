// Forecast-map time navigation, including hour rollover and model-run changes.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('index.html','utf8');
const chunk=(a,b)=>html.slice(html.indexOf(a),html.indexOf(b));
let clock=Date.parse('2026-11-17T16:30:00Z'); // 17:30 CET
class TestDate extends Date {static now(){return clock}}
const controls=new Map(),el=id=>{if(!controls.has(id))controls.set(id,{setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]}});return controls.get(id)};
const ctx=vm.createContext({console,Date:TestDate,Map,Set,Math,Number,atob,el});
vm.runInContext(chunk('const realModelFiles=','async function fetchRealModel')+chunk('const localFormat=','const realPoint=')+`
 let mapSource='model',terrainMode='weather-relief',mapModel='ICON-D2',mapLayer='temp2',mapHour=0,mapTimer=null,mapRegion='Deutschland';
 const fields={temp2:{id:'temp2',interval:0},mlcape:{id:'mlcape',interval:0},rain6:{id:'rain6',interval:6}};
 const stopPlay=()=>{mapTimer=null};
`+chunk('const timeText=d=>','function mapLabels()'),ctx);
const ev=code=>vm.runInContext(code,ctx);
const fixture=(model,run,step,max)=>{const hours=Array.from({length:max/step+1},(_,i)=>i*step);return {model,run,hours,frames:Object.fromEntries(hours.map(h=>[h,{temp2:true,rainTotal:true,...(h%3===0?{mlcape:true}:{})}]))}};
ctx.hourly=fixture('ICON-D2','2026-11-17T12:00:00Z',1,48);ctx.coarse=fixture('GFS','2026-11-17T12:00:00Z',6,48);
ev(`modelDataMode='real';nativeMapModels.set('icon-d2',hourly);nativeMapModels.set('gfs',coarse);syncModelTimeline()`);
assert.equal(ev('mapHour'),5); // 18:00 CET, not 12 UTC initialization
assert.match(controls.get('map-time')['aria-valuetext'],/18:00 Uhr/);
assert.equal(controls.get('map-back').disabled,true);
clock=Date.parse('2026-11-17T17:00:00Z'); // precisely 18:00 CET: next hour only
ev('syncModelTimeline()');assert.equal(ev('mapHour'),6);
clock+=60000;ev('syncModelTimeline()');assert.equal(ev('mapHour'),6);
// Choosing a later valid time must not jump back every hour or on a new run.
ev('selectFutureMapIndex(4)');const selected=ev('mapTargetTime');assert.equal(selected,Date.parse('2026-11-17T22:00:00Z'));
ctx.newRun=fixture('ICON-D2','2026-11-17T15:00:00Z',1,48);
ev("nativeMapModels.set('icon-d2',newRun);syncModelTimeline()");assert.equal(ev('mapHour'),7);assert.equal(ev('modelValidDate().getTime()'),selected);
clock=selected+1;ev('syncModelTimeline()');assert.equal(ev('mapTargetTime'),null);assert.equal(ev('modelValidDate().getTime()'),Date.parse('2026-11-17T23:00:00Z'));
// Skip hours without real parameter data; summation may still use earlier inputs.
ev("mapLayer='mlcape';syncModelTimeline()");assert.equal(ev('mapHour'),9);
ev("mapLayer='rain6';syncModelTimeline()");assert.equal(ev('mapHour'),8);
ev("mapModel='GFS';mapLayer='temp2';syncModelTimeline()");assert.equal(ev('mapHour'),12);assert.equal(ev('modelValidDate().getTime()'),Date.parse('2026-11-18T00:00:00Z'));
clock=Date.parse('2026-11-20T00:00:00Z');ev('syncModelTimeline()');assert.equal(ev('modelValidDate()'),null);assert.equal(controls.get('map-time').disabled,true);assert.equal(controls.get('map-play').disabled,true);
// Mixed real output cadence and per-field sparse output: no invented hours.
clock=Date.parse('2026-11-17T12:00:00Z');
ctx.mixed={model:'GFS',run:'2026-11-17T12:00:00Z',hours:[0,1,2,3,6,9],frames:Object.fromEntries([0,1,2,3,6,9].map(h=>[h,{temp2:true,rainTotal:true}]))};
ev("nativeMapModels.set('gfs-de',mixed);mapModel='GFS';mapTargetTime=null;mapRegion='Deutschland';syncModelTimeline()");
assert.equal(ev('mapHour'),1);assert.equal(ev('mapFutureHours.join()'),'1,2,3,6,9');
assert.equal(ev('mapCadence(mixed,fields.temp2)'),'Original-Zeitschritte: 1 h bis +3 h, danach 3 h');
assert.equal(ev("mapInterval(mixed,'rainrate',6)"),3);assert.equal(ev("mapInterval(mixed,'rainrate',3)"),1);
assert.equal(ev("JSON.stringify(mapFieldRequirements(mixed,{id:'rainrate'},6))"),'[[6,"rainTotal"],[3,"rainTotal"]]');
ev("mixed.frames[2]={wind:true};syncModelTimeline()");assert.equal(ev('mapFutureHours.join()'),'1,3,6,9');
assert.equal(ev("mapInterval(mixed,'rainrate',3)"),2);
ev("mapRegion='Europa';syncModelTimeline()");assert.equal(ev('mapFutureHours.join()'),'6,12,18,24,30,36,42,48');
// The forecast clock must not touch live radar time/navigation.
ev("mapSource='live';mapHour=7;syncModelTimeline()");assert.equal(ev('mapHour'),7);
assert.ok(html.includes("window.addEventListener('focus',()=>{refreshForecastClock();scheduleForecastClock()})"));
console.log('Future-only map times, local hours, exact rollover, manual selection, new run, CAPE gaps, accumulated rain, 6-hour output, expired model and live isolation: OK');

