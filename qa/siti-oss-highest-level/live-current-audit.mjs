import { chromium, devices } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
import path from 'node:path';

const OUT = path.resolve(process.env.AUDIT_OUTPUT || 'artifacts/live-current');
fs.mkdirSync(OUT, { recursive: true });
const results = { generatedAt: new Date().toISOString(), scenarios: [], mutationsBlocked: [], console: [], pageErrors: [] };
const safe = s => s.replace(/[^a-zA-Z0-9_-]+/g, '-');
const save = (n,d) => fs.writeFileSync(path.join(OUT,n), JSON.stringify(d,null,2));

async function axe(page, id) {
  const a = await new AxeBuilder({page}).analyze();
  const v = a.violations.map(x=>({id:x.id,impact:x.impact,help:x.help,nodes:x.nodes.map(n=>({target:n.target,html:n.html,failureSummary:n.failureSummary}))}));
  save(`axe-${safe(id)}.json`,v); return v;
}
async function shot(page,id){const p=path.join(OUT,`${safe(id)}.png`);await page.screenshot({path:p,fullPage:true});return path.basename(p);}
async function inspect(page,id){
  return page.evaluate((scenarioId)=>({
    scenarioId,url:location.href,title:document.title,lang:document.documentElement.lang,
    bodyText:(document.body?.innerText||'').slice(0,20000),
    viewport:{width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight},
    buttons:[...document.querySelectorAll('button')].filter(x=>{const r=x.getBoundingClientRect();return r.width&&r.height}).map(x=>({text:(x.textContent||'').trim(),aria:x.getAttribute('aria-label'),title:x.getAttribute('title')})).slice(0,100),
    links:[...document.querySelectorAll('a')].filter(x=>{const r=x.getBoundingClientRect();return r.width&&r.height}).map(x=>({text:(x.textContent||'').trim(),href:x.href,aria:x.getAttribute('aria-label')})).slice(0,100),
    imagesWithoutAlt:[...document.querySelectorAll('img:not([alt]),img[alt=""]')].length,
    unlabeledButtons:[...document.querySelectorAll('button')].filter(b=>{const t=(b.textContent||'').trim();return !t&&!b.getAttribute('aria-label')&&!b.getAttribute('title')}).length,
    mapCount:document.querySelectorAll('.mapboxgl-map,.leaflet-container,canvas').length,
    hasListAlternative:Boolean(document.querySelector('table,[role="table"],[role="list"],ol,ul')),
    visibleStatusTerms:/verified|unverified|partner|public|updated|reported|diverifikasi|belum diverifikasi|laporan/i.test(document.body?.innerText||''),
  }),id);
}

async function newContext(browser,id,mobile=false){
 const context=await browser.newContext({...(mobile?devices['iPhone 13']:{viewport:{width:1440,height:1000}}),locale:'en-US',timezoneId:'Asia/Jakarta',geolocation:{latitude:-6.175392,longitude:106.827153},permissions:['geolocation']});
 await context.route('**/*',async route=>{
   const r=route.request();
   if(!['GET','HEAD','OPTIONS'].includes(r.method())){results.mutationsBlocked.push({id,method:r.method(),url:r.url(),type:r.resourceType()});return route.abort();}
   return route.continue();
 });
 return context;
}

async function run(browser,id,mobile=false){
 const context=await newContext(browser,id,mobile);const page=await context.newPage();
 page.on('console',m=>{if(['error','warning','warn'].includes(m.type()))results.console.push({id,type:m.type(),text:m.text()})});
 page.on('pageerror',e=>results.pageErrors.push({id,error:String(e)}));
 const row={id,mobile,steps:[],errors:[]};
 try{
  const resp=await page.goto('https://petabencana.id/map?tab=report',{waitUntil:'domcontentloaded',timeout:60000});
  await page.waitForTimeout(8000);
  row.status=resp?.status();row.initial=await inspect(page,id+'-initial');row.initialScreenshot=await shot(page,id+'-initial');row.initialAxe=await axe(page,id+'-initial');
  const report=page.getByRole('button',{name:/KIRIM LAPORAN|SUBMIT REPORT/i}).first();
  row.reportButtonCount=await report.count();
  if(row.reportButtonCount){
    const before=page.url();
    await report.click();await page.waitForTimeout(1800);
    row.afterReport={before,url:page.url(),state:await inspect(page,id+'-after-report'),screenshot:await shot(page,id+'-after-report'),axe:await axe(page,id+'-after-report')};
  }
  const active=page.getByRole('button',{name:/Laporan Aktif|Active Reports/i}).first();
  row.activeButtonCount=await active.count();
  if(row.activeButtonCount){await active.click();await page.waitForTimeout(1000);row.afterActive={state:await inspect(page,id+'-active'),screenshot:await shot(page,id+'-active')};}
  const marker=page.locator('button,[role="button"],div').filter({hasText:/^[1-9]\d*$/}).first();
  row.numericMarkerCount=await marker.count();
  if(row.numericMarkerCount){await marker.click().catch(()=>{});await page.waitForTimeout(700);row.afterMarker={state:await inspect(page,id+'-marker'),screenshot:await shot(page,id+'-marker')};}
  await page.keyboard.press('Tab');
  const focus=[];for(let i=0;i<25;i++){focus.push(await page.evaluate(()=>{const e=document.activeElement;return {tag:e?.tagName,text:(e?.textContent||'').trim().slice(0,120),aria:e?.getAttribute?.('aria-label'),href:e?.getAttribute?.('href')}}));await page.keyboard.press('Tab');}
  row.keyboardOrder=focus;
 }catch(e){row.errors.push(String(e));await shot(page,id+'-failure').catch(()=>{});}
 results.scenarios.push(row);await context.close();
}

const browser=await chromium.launch({headless:true});
try{await run(browser,'current-id-desktop',false);await run(browser,'current-id-mobile',true);}finally{await browser.close();}
results.summary={scenarioCount:results.scenarios.length,scenarioErrors:results.scenarios.filter(x=>x.errors.length).map(x=>({id:x.id,errors:x.errors})),pageErrorCount:results.pageErrors.length,mutationBlockedCount:results.mutationsBlocked.length,productionFingerprint:{framework:'Next.js observed from /_next assets',note:'No public repository-to-production commit mapping was established.'}};
save('live-current-audit.json',results);
fs.writeFileSync(path.join(OUT,'LIVE-CURRENT-SUMMARY.md'),`# Current PetaBencana live read-only audit\n\nGenerated: ${results.generatedAt}\n\nScenarios: ${results.summary.scenarioCount}\nScenario errors: ${results.summary.scenarioErrors.length}\nPage errors: ${results.summary.pageErrorCount}\nNon-GET requests blocked: ${results.summary.mutationBlockedCount}\n\nThe current petabencana.id map serves Next.js assets. The public legacy disastermap repository is therefore not treated as a proven production source match.\n`);
