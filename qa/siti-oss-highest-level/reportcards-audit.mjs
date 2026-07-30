import { chromium, devices } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
import path from 'node:path';

const OUT = path.resolve(process.env.AUDIT_OUTPUT || 'artifacts/browser');
const BASE = process.env.BASE_URL || 'http://127.0.0.1:4200';
fs.mkdirSync(OUT, { recursive: true });

const results = {
  generatedAt: new Date().toISOString(),
  baseUrl: BASE,
  exactTargetCommit: process.env.TARGET_COMMIT || null,
  tests: [],
  browserScenarios: [],
  networkMutations: [],
  pageErrors: [],
  console: [],
  sourceFindings: [],
};

function record(id, title, status, severity, evidence = {}, recommendation = '') {
  results.tests.push({ id, title, status, severity, evidence, recommendation });
}
function safe(s) { return String(s).replace(/[^a-zA-Z0-9_-]+/g, '-'); }
function write(name, data) { fs.writeFileSync(path.join(OUT, name), typeof data === 'string' ? data : JSON.stringify(data, null, 2)); }
async function shot(page, name, fullPage = true) {
  const file = path.join(OUT, `${safe(name)}.png`);
  await page.screenshot({ path: file, fullPage });
  return path.basename(file);
}
async function axe(page, name) {
  try {
    const a = await new AxeBuilder({ page }).analyze();
    const v = a.violations.map(x => ({ id: x.id, impact: x.impact, help: x.help, nodes: x.nodes.map(n => ({ target: n.target, html: n.html, failureSummary: n.failureSummary })) }));
    write(`axe-${safe(name)}.json`, v);
    return v;
  } catch (e) { return [{ id: 'audit-error', impact: 'unknown', help: String(e), nodes: [] }]; }
}

const mocked = { regions: [{ code: 'JKT', name: 'Jakarta', geometry: null }, { code: 'BDG', name: 'Bandung', geometry: null }] };

async function installRoutes(context, scenario) {
  await context.route('**/*', async route => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const mutating = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    if (mutating) results.networkMutations.push({ scenario, method, url, headers: req.headers(), postData: req.postData() });

    if (url.startsWith('https://nominatim.openstreetmap.org/search')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ place_id: 1, lat: '-6.175392', lon: '106.827153', display_name: 'Jakarta, Indonesia', type: 'city', importance: 1 }]) });
    }
    if (url.startsWith('https://nominatim.openstreetmap.org/reverse')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ address: { country_code: 'id', city: 'Jakarta', country: 'Indonesia' }, display_name: 'Jakarta, Indonesia' }) });
    }
    if (url.startsWith('https://api.mapbox.com/geocoding/')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ features: [{ id: 'postcode.12345', place_name: 'Jakarta 10110, Indonesia', context: [{ id: 'postcode.10110' }, { id: 'place.jakarta', text: 'Jakarta' }, { id: 'region.jakarta', text: 'DKI Jakarta' }] }] }) });
    }
    if (url.startsWith('https://api.petabencana.id/cards/test123/images')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ signedRequest: 'https://audit-upload.invalid/object' }) });
    }
    if (url.startsWith('https://audit-upload.invalid/')) {
      const body = req.postDataBuffer();
      write(`${safe(scenario)}-uploaded-image.bin`, body || Buffer.alloc(0));
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    }
    if (url.startsWith('https://api.petabencana.id/')) {
      if (url.includes('/cards/') && method === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ result: { received: false, language: 'en', network: 'audit' } }) });
      }
      if (url.endsWith('/regions') || url.includes('/regions?')) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ result: mocked.regions }) });
      }
      if (url.includes('/subscriptions/regions')) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ result: [] }) });
      }
      if (url.includes('/needs/')) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ result: [], success: true }) });
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ result: {}, success: true }) });
    }
    if (/google-analytics|googletagmanager|doubleclick/.test(url)) return route.abort();
    return route.continue();
  });
}

async function makeContext(browser, scenario, mobile = false) {
  const context = await browser.newContext({
    ...(mobile ? devices['iPhone 13'] : { viewport: { width: 1440, height: 1100 } }),
    geolocation: { latitude: -6.175392, longitude: 106.827153 },
    permissions: ['geolocation'], locale: 'en-US', timezoneId: 'Asia/Jakarta', acceptDownloads: true,
  });
  await installRoutes(context, scenario);
  return context;
}

function observe(page, scenario) {
  page.on('pageerror', e => results.pageErrors.push({ scenario, error: String(e), stack: e.stack }));
  page.on('console', m => { if (['error', 'warning', 'warn'].includes(m.type())) results.console.push({ scenario, type: m.type(), text: m.text() }); });
}

async function waitApp(page) {
  await page.waitForLoadState('domcontentloaded');
  await page.locator('app-root').waitFor({ state: 'attached', timeout: 30000 });
  await page.waitForTimeout(1200);
}
async function goto(page, route) {
  const response = await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await waitApp(page);
  return response?.status() ?? null;
}
async function clickTraining(page) {
  const b = page.getByRole('button', { name: /Complete Training Exercise|Latihan Simulasi/i }).first();
  if (await b.count()) { await b.click(); await page.waitForTimeout(250); return true; }
  return false;
}
async function clickReal(page) {
  const b = page.getByRole('button', { name: /Submit Disaster Report|Laporkan Bencana/i }).first();
  if (await b.count()) { await b.click(); await page.waitForTimeout(250); return true; }
  return false;
}
function next(page) { return page.getByRole('button', { name: /^(NEXT|LANJUTKAN)$/i }).last(); }
async function dragMarker(page) {
  const marker = page.locator('.mapboxgl-marker').first();
  await marker.waitFor({ state: 'visible', timeout: 30000 });
  const box = await marker.boundingBox();
  if (!box) throw new Error('Map marker has no bounding box');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 35, box.y + box.height / 2 + 20, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(400);
}
async function progressFloodToDescription(page, reportKind = 'training') {
  await goto(page, '/test123/flood/location');
  reportKind === 'training' ? await clickTraining(page) : await clickReal(page);
  await dragMarker(page);
  const n1 = next(page); await n1.waitFor({ state: 'visible' });
  if (await n1.isDisabled()) throw new Error('NEXT stayed disabled after marker drag');
  await n1.click();
  await page.locator('#cardContentWrapper').waitFor({ state: 'visible' });
  await page.locator('#cardContentWrapper').click({ position: { x: 20, y: 20 } });
  if (await next(page).isDisabled()) throw new Error('NEXT stayed disabled on depth card after interaction');
  await next(page).click();
  await page.locator('#image-uploader-button').waitFor({ state: 'attached' });
  await next(page).click();
  await page.locator('textarea').waitFor({ state: 'visible' });
}

async function floodTextFlow(browser, mobile = false) {
  const scenario = mobile ? 'flood-training-mobile' : 'flood-training-desktop';
  const context = await makeContext(browser, scenario, mobile);
  const page = await context.newPage(); observe(page, scenario);
  const entry = { scenario, steps: [], errors: [] };
  try {
    await progressFloodToDescription(page, 'training');
    await page.locator('textarea').fill('<img src=x onerror=window.__audit_xss=1> audit description');
    entry.descriptionMaxLength = await page.locator('textarea').getAttribute('maxlength');
    await next(page).click();
    await page.getByText(/Review & Submit|Tinjau/).first().waitFor({ state: 'visible', timeout: 15000 });
    entry.reviewScreenshot = await shot(page, `${scenario}-review`);
    entry.axe = await axe(page, `${scenario}-review`);
    entry.xssExecuted = await page.evaluate(() => Boolean(window.__audit_xss));
    entry.reviewTextContainsLiteralMarkup = (await page.locator('body').innerText()).includes('<img src=x');
    const termsLink = page.getByText(/terms|ketentuan/i).first();
    if (await termsLink.count()) {
      await termsLink.click(); await page.waitForTimeout(200);
      entry.termsVisible = await page.locator('#termsPopup').isVisible();
      entry.termsScreenshot = await shot(page, `${scenario}-terms`);
      const close = page.getByText(/Close/i).last(); if (await close.count()) await close.click();
    }
    const submit = page.getByRole('button', { name: /Complete Training|Selesaikan Latihan/i }).last();
    entry.submitEnabled = !(await submit.isDisabled());
    await Promise.all([submit.click(), submit.click().catch(() => {})]);
    await page.waitForTimeout(1200);
    entry.finalUrl = page.url();
    entry.thankVisible = /thank/.test(page.url()) || /Thank you|Terima Kasih/i.test(await page.locator('body').innerText());
    entry.finalScreenshot = await shot(page, `${scenario}-thank`);
    const puts = results.networkMutations.filter(x => x.scenario === scenario && x.method === 'PUT' && /api\.petabencana\.id\/cards\/test123$/.test(x.url));
    entry.reportPutCount = puts.length;
    entry.reportPayload = puts[0]?.postData ? JSON.parse(puts[0].postData) : null;
    record(`RC-${mobile ? 'M' : 'D'}-001`, `${mobile ? 'Mobile' : 'Desktop'} flood training flow reaches review and thank`, entry.thankVisible ? 'EXECUTED_PASS' : 'EXECUTED_FAIL', entry.thankVisible ? 'P2' : 'P0', entry, 'Keep this end-to-end training flow as a release regression test.');
    record(`RC-${mobile ? 'M' : 'D'}-002`, 'Double-click submission is locally deduplicated', entry.reportPutCount === 1 ? 'EXECUTED_PASS' : 'EXECUTED_FAIL', entry.reportPutCount === 1 ? 'P2' : 'P0', { reportPutCount: entry.reportPutCount }, 'Retain client guard and add server-side idempotency.');
    record(`RC-${mobile ? 'M' : 'D'}-003`, 'Description markup is rendered as text, not executed', !entry.xssExecuted ? 'EXECUTED_PASS' : 'EXECUTED_FAIL', !entry.xssExecuted ? 'P2' : 'P0', { xssExecuted: entry.xssExecuted, literal: entry.reviewTextContainsLiteralMarkup }, 'Keep interpolation and add server-side sanitization.');
  } catch (e) {
    entry.errors.push(String(e));
    await shot(page, `${scenario}-failure`).catch(() => null);
    record(`RC-${mobile ? 'M' : 'D'}-001`, `${mobile ? 'Mobile' : 'Desktop'} flood training flow reaches review and thank`, 'EXECUTED_FAIL', 'P0', { error: String(e), url: page.url() }, 'Fix the broken flow and preserve this regression test.');
  }
  results.browserScenarios.push(entry);
  await context.close();
}

async function realReportClassification(browser) {
  const scenario = 'real-report-training-word-classification';
  const context = await makeContext(browser, scenario, false);
  const page = await context.newPage(); observe(page, scenario);
  const entry = { scenario, errors: [] };
  try {
    await progressFloodToDescription(page, 'real');
    await page.locator('textarea').fill('A peaceful protest is taking place near the flooded road.');
    await next(page).click();
    const submit = page.getByRole('button', { name: /Submit Report|Kirim Laporan/i }).last();
    await submit.click(); await page.waitForTimeout(1000);
    const put = results.networkMutations.find(x => x.scenario === scenario && x.method === 'PUT' && /\/cards\/test123$/.test(x.url));
    entry.payload = put?.postData ? JSON.parse(put.postData) : null;
    entry.isTraining = entry.payload?.is_training;
    record('RC-CLS-001', 'Real report containing an incidental training substring stays real', entry.isTraining === false ? 'EXECUTED_PASS' : 'EXECUTED_FAIL', entry.isTraining === false ? 'P2' : 'P0', entry, 'Replace substring matching with explicit report-type state; never infer training from free text.');
  } catch (e) {
    entry.errors.push(String(e));
    record('RC-CLS-001', 'Real report containing an incidental training substring stays real', 'EXECUTED_FAIL', 'P0', { error: String(e) }, 'Fix flow, then replace substring inference with explicit report type.');
  }
  results.browserScenarios.push(entry); await context.close();
}

function syntheticJpeg() {
  const marker = Buffer.from('AUDIT_EXIF_GPS_SENTINEL=lat:-6.175392,lng:106.827153');
  return Buffer.concat([Buffer.from([0xff,0xd8,0xff,0xe1,0x00,marker.length + 2]), marker, Buffer.from([0xff,0xd9])]);
}
async function photoMetadataFlow(browser) {
  const scenario = 'photo-metadata-upload';
  const context = await makeContext(browser, scenario, false);
  const page = await context.newPage(); observe(page, scenario);
  const entry = { scenario, errors: [] };
  try {
    await goto(page, '/test123/flood/location'); await clickTraining(page); await dragMarker(page); await next(page).click();
    await page.locator('#cardContentWrapper').click({ position: { x: 20, y: 20 } }); await next(page).click();
    const p = path.join(OUT, 'synthetic-exif-gps.jpg'); fs.writeFileSync(p, syntheticJpeg());
    await page.locator('#image-uploader-button').setInputFiles({ name: 'synthetic-exif-gps.jpg', mimeType: 'image/jpeg', buffer: fs.readFileSync(p) });
    await page.waitForTimeout(700); await next(page).click();
    await next(page).click();
    const submit = page.getByRole('button', { name: /Complete Training|Selesaikan Latihan/i }).last();
    await submit.click(); await page.waitForTimeout(1200);
    const uploaded = path.join(OUT, `${safe(scenario)}-uploaded-image.bin`);
    const bytes = fs.existsSync(uploaded) ? fs.readFileSync(uploaded) : Buffer.alloc(0);
    entry.uploadBytes = bytes.length;
    entry.metadataSentinelPreserved = bytes.includes(Buffer.from('AUDIT_EXIF_GPS_SENTINEL'));
    record('RC-IMG-001', 'Photo upload strips metadata before network transfer', entry.metadataSentinelPreserved ? 'EXECUTED_FAIL' : 'EXECUTED_PASS', entry.metadataSentinelPreserved ? 'P0' : 'P2', entry, 'Decode and re-encode images server-side; strip EXIF/GPS and validate decoded dimensions.');
  } catch (e) {
    entry.errors.push(String(e));
    record('RC-IMG-001', 'Photo upload strips metadata before network transfer', 'BLOCKED', 'P1', { error: String(e) }, 'Complete the photo flow in sandbox and verify server-side re-encoding.');
  }
  results.browserScenarios.push(entry); await context.close();
}

async function semanticsAndRoutes(browser) {
  const context = await makeContext(browser, 'route-inventory', false);
  const page = await context.newPage(); observe(page, 'route-inventory');
  const routes = {
    flood: ['location','depth','photo','description','review'], fire: ['firedistance','fireestimate','photo','description','review'],
    haze: ['location','visibility','airquality','photo','description','review'], earthquake: ['type','location','structure','accessibility','condition','photo','description','review'],
    wind: ['location','impact','photo','description','review'], volcano: ['location','sign','photo','description','evacuationnumber','evacuationarea','review'],
    notifications: ['region','summary'], need: ['location','products','productreview'], giver: ['donate','dateandtime','contact','donationreview'],
  };
  const inventory = [];
  for (const [deck, cards] of Object.entries(routes)) {
    for (const card of cards) {
      const row = { deck, card, route: `/test123/${deck}/${card}`, errors: [] };
      try {
        await goto(page, row.route);
        await clickTraining(page).catch(() => false);
        row.url = page.url(); row.titleText = (await page.locator('body').innerText()).slice(0, 800);
        row.horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
        row.buttons = await page.locator('button').evaluateAll(bs => bs.map(b => ({ text: (b.textContent || '').trim(), disabled: b.disabled, aria: b.getAttribute('aria-label') })));
        row.inputs = await page.locator('input,textarea,select').evaluateAll(xs => xs.map(x => ({ tag: x.tagName, type: x.getAttribute('type'), name: x.getAttribute('name'), aria: x.getAttribute('aria-label'), labelledBy: x.getAttribute('aria-labelledby') })));
        row.axe = (await axe(page, `route-${deck}-${card}`)).map(v => v.id);
      } catch (e) { row.errors.push(String(e)); }
      inventory.push(row);
    }
  }
  write('route-inventory.json', inventory);
  record('RC-ROUTE-001', 'All configured card routes render without uncaught errors', inventory.every(x => x.errors.length === 0) ? 'EXECUTED_PASS' : 'EXECUTED_FAIL', inventory.every(x => x.errors.length === 0) ? 'P2' : 'P1', { failed: inventory.filter(x => x.errors.length).map(x => ({ route: x.route, errors: x.errors })) }, 'Add route-level smoke tests for every configured deck and card.');
  const semanticRoutes = [['/test123/earthquake/type', 'app-type-button .type'], ['/test123/volcano/sign', '.option'], ['/test123/volcano/evacuationnumber', '.option'], ['/test123/haze/airquality', '.airquality__type']];
  const semantic = [];
  for (const [r, selector] of semanticRoutes) {
    try {
      await goto(page, r); await clickTraining(page).catch(() => false);
      const nodes = await page.locator(selector).evaluateAll(xs => xs.map(x => ({ tag: x.tagName, role: x.getAttribute('role'), tabindex: x.getAttribute('tabindex') })));
      semantic.push({ route: r, selector, nodes });
    } catch (e) { semantic.push({ route: r, selector, error: String(e) }); }
  }
  write('keyboard-semantics.json', semantic);
  const bad = semantic.flatMap(x => x.nodes || []).filter(n => !['BUTTON','A','INPUT','SELECT','TEXTAREA'].includes(n.tag) && n.role !== 'button' && n.tabindex !== '0');
  record('RC-A11Y-001', 'Custom option controls are keyboard-operable and expose button semantics', bad.length === 0 ? 'EXECUTED_PASS' : 'EXECUTED_FAIL', bad.length === 0 ? 'P2' : 'P1', { semantic, nonSemanticCount: bad.length }, 'Use native buttons or add role, tabindex, Enter/Space handlers, focus styles, and selected state.');
  await context.close();
}

async function offlineAndInvalidOtl(browser) {
  const context = await makeContext(browser, 'resilience', false); const page = await context.newPage(); observe(page, 'resilience');
  try {
    await goto(page, '/test123/flood/location');
    await context.setOffline(true); await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => null); await page.waitForTimeout(500);
    const body = await page.locator('body').innerText().catch(() => '');
    record('RC-OFF-001', 'Previously loaded report flow has a useful offline reload state', body.trim().length > 20 ? 'EXECUTED_PASS' : 'EXECUTED_FAIL', body.trim().length > 20 ? 'P2' : 'P1', { bodyPrefix: body.slice(0,300), url: page.url() }, 'Provide explicit offline/retry state and preserve unsent draft locally.');
    await context.setOffline(false);
    await goto(page, '/unknown-token/flood/location'); await page.waitForTimeout(400);
    const invalidBody = await page.locator('body').innerText();
    record('RC-AUTH-001', 'Invalid one-time link fails closed', /error|invalid|unknown/i.test(invalidBody) ? 'EXECUTED_PASS' : 'EXECUTED_FAIL', /error|invalid|unknown/i.test(invalidBody) ? 'P2' : 'P0', { bodyPrefix: invalidBody.slice(0,500), url: page.url() }, 'Keep OTL validation fail-closed and add explicit user guidance.');
  } catch (e) { record('RC-OFF-001', 'Offline and invalid-link resilience', 'BLOCKED', 'P1', { error: String(e) }, 'Add deterministic resilience tests.'); }
  await context.close();
}

async function sourceChecks() {
  const root = process.env.TARGET_ROOT;
  if (!root) return;
  const read = p => fs.readFileSync(path.join(root, p), 'utf8');
  const deck = read('src/app/services/cards/deck.service.ts');
  const giver = read('src/app/routes/decks/giver/giver.component.ts');
  const review = read('src/app/routes/cards/review/review.component.html');
  const env = read('src/environments/id/environment.ts');
  const checks = {
    captchaDisabled: /Captcha disabled/.test(review) && /captchaCleared = true/.test(deck),
    substringTrainingInference: /str\.toLowerCase\(\)\.includes/.test(deck) && /containsTrainingWord\(this\.description\)/.test(deck),
    giverTrainingForcedReal: /onTypeSelected\(type\)[\s\S]{0,180}selectReportType\('real'\)/.test(giver),
    preciseNeedLocationAndAddress: /lng: this\.location\.lng/.test(deck) && /address: this\.address/.test(deck),
    predictableDeliveryCode: /delivery_code: 'code-'/.test(deck),
    publicMapboxToken: /mapbox_access_token/.test(env),
    noIdempotencyKeyword: !/idempotency|idempotency-key/i.test(deck),
  };
  write('source-checks.json', checks);
  record('RC-SRC-001', 'CAPTCHA removal has a repository-verifiable replacement control', checks.captchaDisabled ? 'SOURCE_RISK' : 'NOT_OBSERVED', 'P0', checks, 'Document and automatically test API-gateway rate-limit contracts per deployment.');
  record('RC-SRC-002', 'Training status is determined only by explicit user choice', checks.substringTrainingInference ? 'SOURCE_FAIL' : 'SOURCE_PASS', checks.substringTrainingInference ? 'P0' : 'P2', checks, 'Remove free-text substring inference.');
  record('RC-SRC-003', 'Giver training selection is respected', checks.giverTrainingForcedReal ? 'SOURCE_FAIL' : 'SOURCE_PASS', checks.giverTrainingForcedReal ? 'P1' : 'P2', checks, 'Pass the selected type instead of hard-coding real.');
  record('RC-SRC-004', 'Need and giver requests minimize precise personal/location data', checks.preciseNeedLocationAndAddress ? 'SOURCE_RISK' : 'SOURCE_PASS', 'P0', checks, 'Separate public approximate geometry from restricted responder geometry and minimize address/contact fields.');
  record('RC-SRC-005', 'Submission contract includes an idempotency key', checks.noIdempotencyKeyword ? 'SOURCE_FAIL' : 'SOURCE_PASS', checks.noIdempotencyKeyword ? 'P0' : 'P2', checks, 'Add client request IDs and server idempotency.');
}

async function main() {
  await sourceChecks();
  const browser = await chromium.launch({ headless: true });
  try {
    await floodTextFlow(browser, false); await floodTextFlow(browser, true); await realReportClassification(browser); await photoMetadataFlow(browser); await semanticsAndRoutes(browser); await offlineAndInvalidOtl(browser);
  } finally { await browser.close(); }
  results.summary = {
    count: results.tests.length,
    statusCounts: results.tests.reduce((a,x)=>(a[x.status]=(a[x.status]||0)+1,a),{}),
    severityCounts: results.tests.reduce((a,x)=>(a[x.severity]=(a[x.severity]||0)+1,a),{}),
    p0Findings: results.tests.filter(x => x.severity === 'P0' && !String(x.status).includes('PASS')).map(x => ({ id:x.id,title:x.title,status:x.status })),
    mutationCount: results.networkMutations.length, pageErrorCount: results.pageErrors.length,
  };
  write('reportcards-audit-results.json', results);
  const lines = ['# Siti OSS Report Cards executed audit', '', `Generated: ${results.generatedAt}`, '', `Tests: ${results.summary.count}`, `P0 unresolved: ${results.summary.p0Findings.length}`, '', '## P0 findings', ...results.summary.p0Findings.map(x => `- ${x.id}: ${x.title} (${x.status})`)];
  write('REPORTCARDS-AUDIT-SUMMARY.md', lines.join('\n'));
  if (results.tests.length < 10) process.exitCode = 2;
}
main().catch(e => { write('fatal.txt', e?.stack || String(e)); process.exitCode = 2; });
