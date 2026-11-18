// Targeted smoke checks, independent from changing numerical forecast snapshots.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const hazards=fs.readFileSync('assets/hazards.js','utf8');
for(const fragment of ['id="page-hazards"','id="hazard-road-content"','id="hazard-water-content"','data-hazard-tab="road"','data-hazard-tab="water"','getLocation:()=>({...location})','window.WeatherHazards?.open()','assets/hazards.js']){
  assert.ok(html.includes(fragment),'UI missing '+fragment);
}
new vm.Script(hazards,{filename:'assets/hazards.js'});
assert.match(hazards,/pegelonline\.wsv\.de/);
assert.match(hazards,/data\/road-weather\.json/);
assert.match(hazards,/stateMnwMhw/);
assert.match(hazards,/MAX_ROAD_DISTANCE = 55/);
console.log('Road/flood pages, wiring, official sources and JS syntax: OK');
