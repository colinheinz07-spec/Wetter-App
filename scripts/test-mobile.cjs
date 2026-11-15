// Run from repo root with Playwright and Chromium. Requires published IFS grid.
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const stations=JSON.parse(fs.readFileSync('data/stations.json','utf8'));
const ifs=JSON.parse(fs.readFileSync('data/ifs.json','utf8'));
// A tiny test image exercises the fallback only; production uses DWD PNGs.
const fixedTime=new Date(Date.parse(ifs.generated)+60000);
const snapshotTime=new Date(Math.floor((fixedTime.getTime()-10*60000)/300000)*300000);
stations.radarBase=snapshotTime.toISOString();
stations.radarImage={time:snapshotTime.toISOString(),bounds:[2,45,18,57],png:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR1sAAAAASUVORK5CYII='};
const server=http.createServer((req,res)=>{
 const p=path.resolve('.','.'+new URL(req.url,'http://localhost').pathname);
 if(!p.startsWith(process.cwd()+path.sep)){res.writeHead(403).end();return}
 if(!fs.existsSync(p)||!fs.statSync(p).isFile()){res.writeHead(404).end();return}
 res.setHeader('Content-Type',p.endsWith('.html')?'text/html':p.endsWith('.js')?'text/javascript':p.endsWith('.json')?'application/json':'application/octet-stream');
 fs.createReadStream(p).pipe(res);
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const url='http://127.0.0.1:'+server.address().port;
 const executablePath=process.env.CHROMIUM_PATH|| (fs.existsSync(chromium.executablePath())?chromium.executablePath():'/usr/bin/chromium');
 const browser=await chromium.launch({executablePath,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.clock.setFixedTime(fixedTime);
  await page.route('**/*',route=>{
   const u=route.request().url();
   if(u.endsWith('/data/stations.json'))return route.fulfill({json:stations});
   if(u.endsWith('/data/live-imagery.json'))return route.fulfill({json:{schema:1,products:{reflectivity:{...stations.radarImage,source:'DWD DMAX'},satellite:{...stations.radarImage,source:'EUMETSAT / NASA'}}}});
   if(u.startsWith(url))return route.continue();
   return route.abort();
  });
  await page.goto(url+'/index.html');
  await page.waitForFunction(()=>document.querySelectorAll('.real-day').length===7&&[...document.querySelectorAll('.real-day')].some(x=>x.innerText.includes('IFS')),{},{timeout:45000});
  const rows=await page.locator('.real-day').allTextContents();
  assert.equal(rows.length,7);assert.ok(rows.every(x=>!x.includes('Keine Daten')),rows.join('\n'));
  assert.ok(rows[0].includes('Heute')&&!rows[0].includes('Keine Daten'));
  const temperatures=await page.locator('.hour strong,.real-day .tempgroup span,.hero .temp').allTextContents();
  assert.ok(temperatures.every(x=>!/\d[,.]\d/.test(x)),temperatures.join(' / '));
  assert.equal(await page.locator('.real-day .day-icon img').count(),7);
  assert.equal(await page.locator('.hour img').count(),await page.locator('.hour').count());
  await page.waitForFunction(()=>[...document.querySelectorAll('.real-day img,.hour img')].every(i=>i.complete&&i.naturalWidth>0));
  await page.locator('.real-day').nth(2).click();
  assert.ok(await page.locator('.day-hour-header img').count()>0);
  await page.waitForFunction(()=>document.querySelector('#home-value-radar')?.innerText.startsWith('DWD ·'),{},{timeout:25000});
  for(const width of [390,320,430,900]){
   await page.setViewportSize({width,height:844});
   const layout=await page.evaluate(()=>({window:innerWidth,scroll:document.documentElement.scrollWidth,hero:document.querySelector('.hero').getBoundingClientRect().width,right:document.querySelector('.forecast').getBoundingClientRect().width,grid:document.querySelector('.main-grid').getBoundingClientRect().width}));
   assert.ok(layout.scroll<=layout.window+1,JSON.stringify(layout));
   if(width<760){assert.ok(layout.hero>=layout.grid-2,JSON.stringify(layout));assert.ok(layout.right>=layout.grid-2,JSON.stringify(layout))}
  }
  await page.setViewportSize({width:390,height:844});
  await page.locator('.forecast').scrollIntoViewIfNeeded();
  if(process.env.WEATHER_TEST_SCREENSHOT)await page.screenshot({path:process.env.WEATHER_TEST_SCREENSHOT});
  await page.evaluate(()=>{setPage('map');setMapSource('live');selectLiveLayer('reflectivity')});
  await page.waitForFunction(()=>document.querySelector('#map-data-notice').textContent==='Beobachtung');
  assert.match(await page.locator('#legend-unit').textContent(),/dBZ/);
  assert.equal(await page.locator('#map-time-controls').isVisible(),false);
  await page.evaluate(()=>selectLiveLayer('satellite'));
  await page.waitForFunction(()=>document.querySelector('#map-data-notice').textContent==='Beobachtung');
  assert.match(await page.locator('#map-view-description').textContent(),/EUMETSAT/);
  await page.evaluate(()=>setMapSource('model'));
  assert.equal(await page.locator('#map-time-controls').isVisible(),true);
  assert.deepEqual(errors,[]);console.log('Mobile widths, actual seven-day IFS forecast and radar image fallback: OK');
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);server.close();process.exitCode=1});
