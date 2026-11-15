// Test the actual browser data contract and selection functions without a DOM.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('index.html','utf8');
const chunk = (from,to) => html.slice(html.indexOf(from),html.indexOf(to));
const context = vm.createContext({console,Date,atob,Int16Array,Map,Set,Math,Number});
vm.runInContext(chunk('const realModelFiles=','async function fetchRealModel') + chunk('const localDay=','const realPoint=')+
  chunk('const realPoint=','function frameWeather'),context);
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
console.log('Existing ICON grids, IFS schema, model transitions, precipitation and missing fields: OK');
if(fs.existsSync('data/ifs.json')){
 const actual=JSON.parse(fs.readFileSync('data/ifs.json','utf8'));
 Object.assign(context,{actual,now:Date.parse(actual.generated),berlin:[13.4,52.52]});
 vm.runInContext('realModelCache.set("IFS",validateRealData(actual,"IFS"));realDecoded.clear()',context);
 const days=vm.runInContext(`const rows=modelLocationFrames(berlin,now,true);Array.from({length:7},(_,i)=>rows.filter(f=>localDay(f.time)===localDay(now+i*86400000)).map(f=>f.d.model))`,context);
 assert.ok(days.every(d=>d.length),JSON.stringify(days));assert.ok(days[6].includes('IFS'));
 console.log('Real published IFS + ICON: seven days including late-evening Today: OK');
}
