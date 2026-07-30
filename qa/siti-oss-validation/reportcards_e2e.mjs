import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const appURL = (process.env.REPORTCARDS_URL || 'http://127.0.0.1:4200').replace(/\/$/, '');
const apiURL = (process.env.SITI_SERVER_URL || 'http://127.0.0.1:8001').replace(/\/$/, '');
const outDir = path.resolve(process.env.SITI_VALIDATION_OUT || 'artifacts/reportcards-e2e');
fs.mkdirSync(outDir, { recursive: true });

const validPng = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=', 'base64');
const fakeExifJpeg = Buffer.concat([
  Buffer.from([0xff, 0xd8, 0xff, 0xe1, 0x00, 0x3c]),
  Buffer.from('Exif\u0000\u0000SITI_AUDIT_GPSLatitude=-6.175392;GPSLongitude=106.827153;', 'utf8'),
  Buffer.from([0xff, 0xd9]),
]);
const files = {
  valid: { name: 'valid.png', mimeType: 'image/png', buffer: validPng },
  disguised: { name: 'disguised.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('<html><script>window.__siti_bad=1</script></html>') },
  oversized: { name: 'oversized.jpg', mimeType: 'image/jpeg', buffer: Buffer.alloc(12 * 1024 * 1024, 0x41) },
  exif: { name: 'gps-exif.jpg', mimeType: 'image/jpeg', buffer: fakeExifJpeg },
};

function save(name, value) {
  fs.writeFileSync(path.join(outDir, name), JSON.stringify(value, null, 2));
}

function nextButton(page) {
  return page.locator('button:visible').filter({ hasText: /NEXT/i }).first();
}

async function api(method, route, body) {
  const response = await fetch(apiURL + route, {
    method,
    headers: { 'content-type': 'application/json', 'user-agent': 'SitiOSS-Local-E2E/2026-07-30' },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data;
  try { data = await response.json(); } catch { data = await response.text(); }
  return { status: response.status, data };
}

async function createCard(label) {
  const result = await api('POST', '/cards', { username: `e2e-${label}`, network: 'twitter', language: 'en', network_data: {} });
  if (result.status !== 200) throw new Error(`card creation failed: ${JSON.stringify(result)}`);
  return result.data.cardId;
}

async function clickTraining(page) {
  const button = page.getByRole('button', { name: /Complete Training Exercise/i });
  await button.waitFor({ state: 'visible', timeout: 15000 });
  await button.click();
}

async function enableLocation(page) {
  const search = page.locator('input[name=search]');
  await search.waitFor({ state: 'visible', timeout: 15000 });
  await search.fill('Monumen Nasional');
  const option = page.locator('.dynamic-search-results__result').first();
  await option.waitFor({ state: 'visible', timeout: 15000 });
  await option.click();
  await page.waitForTimeout(900);

  const marker = page.locator('.mapboxgl-marker').last();
  await marker.waitFor({ state: 'visible', timeout: 15000 });
  const box = await marker.boundingBox();
  if (!box) throw new Error('marker has no bounding box');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 110, box.y + box.height / 2 - 75, { steps: 14 });
  await page.mouse.up();
  await page.waitForTimeout(700);

  const next = nextButton(page);
  await next.waitFor({ state: 'visible', timeout: 15000 });
  if (await next.isDisabled()) {
    const debug = await page.evaluate(() => ({
      buttons: [...document.querySelectorAll('button')].map(button => ({ text: button.textContent?.trim(), disabled: button.disabled, className: button.className })),
      markers: [...document.querySelectorAll('.mapboxgl-marker')].map(markerElement => ({ html: markerElement.outerHTML.slice(0, 1000), transform: getComputedStyle(markerElement).transform })),
    }));
    throw new Error(`NEXT remained disabled after searched-location marker drag: ${JSON.stringify(debug)}`);
  }
  await next.click();
}

async function setDepthAndNext(page) {
  await page.waitForURL(/\/depth(?:\?|$)/, { timeout: 15000 });
  const zone = page.locator('#sliderZone');
  await zone.waitFor({ state: 'visible', timeout: 15000 });
  const box = await zone.boundingBox();
  if (!box) throw new Error('depth slider has no box');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 - 35, { steps: 5 });
  await page.mouse.up();
  const next = nextButton(page);
  await page.waitForTimeout(250);
  if (await next.isDisabled()) throw new Error('NEXT remained disabled after depth interaction');
  await next.click();
}

async function photoAndDescription(page, uploadMode) {
  await page.waitForURL(/\/photo(?:\?|$)/, { timeout: 15000 });
  if (uploadMode) {
    await page.locator('input[type=file]').setInputFiles(files[uploadMode]);
    await page.waitForTimeout(uploadMode === 'oversized' ? 1800 : 900);
  }
  await nextButton(page).click();
  await page.waitForURL(/\/description(?:\?|$)/, { timeout: 15000 });
  await page.locator('textarea[name=textbox]').fill(`SITI E2E ${uploadMode || 'no-image'} ${new Date().toISOString()}`);
  await nextButton(page).click();
}

async function submitReview(page, doubleSubmit) {
  await page.waitForURL(/\/review(?:\?|$)/, { timeout: 15000 });
  const submit = page.locator('app-submit-button button:visible').first();
  await submit.waitFor({ state: 'visible', timeout: 15000 });
  if (await submit.isDisabled()) throw new Error('review submit button is disabled');
  if (doubleSubmit) {
    await Promise.allSettled([submit.click({ noWaitAfter: true }), submit.click({ noWaitAfter: true })]);
  } else {
    await submit.click({ noWaitAfter: true });
  }
  await page.waitForURL(/\/thank(?:\?|$)/, { timeout: 15000 }).catch(() => null);
  await page.waitForTimeout(1600);
}

async function runScenario(browser, scenario) {
  const cardId = await createCard(scenario.id);
  const context = await browser.newContext({
    viewport: { width: 1365, height: 900 },
    geolocation: { latitude: -6.175392, longitude: 106.827153 },
    permissions: ['geolocation'],
  });
  const page = await context.newPage();
  const network = [];
  const consoleMessages = [];
  const pageErrors = [];
  const s3Uploads = [];
  let reportPutCount = 0;
  let reportPatchCount = 0;
  let abortedReport = false;

  page.on('console', message => consoleMessages.push({ type: message.type(), text: message.text() }));
  page.on('pageerror', error => pageErrors.push(String(error)));
  page.on('request', request => {
    const url = request.url();
    if (url.startsWith(apiURL)) network.push({ phase: 'request', method: request.method(), url, postData: request.postData() });
  });
  page.on('response', response => {
    const url = response.url();
    if (url.startsWith(apiURL)) network.push({ phase: 'response', status: response.status(), url });
  });

  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    if (url.origin === apiURL && url.pathname === `/cards/${cardId}` && method === 'PUT') {
      reportPutCount += 1;
      if (scenario.abortReport && !abortedReport) {
        abortedReport = true;
        return route.abort('internetdisconnected');
      }
      return route.continue();
    }
    if (url.origin === apiURL && url.pathname === `/cards/${cardId}` && method === 'PATCH') {
      reportPatchCount += 1;
      return route.continue();
    }
    if (/amazonaws\.com$/.test(url.hostname) && method === 'PUT') {
      const bytes = request.postDataBuffer();
      s3Uploads.push({
        url: request.url(),
        contentType: request.headers()['content-type'],
        bytes: bytes?.length || 0,
        prefixHex: bytes?.subarray(0, 96).toString('hex') || '',
        containsAuditGPS: bytes ? bytes.includes(Buffer.from('SITI_AUDIT_GPSLatitude')) : false,
        containsHTMLScript: bytes ? bytes.includes(Buffer.from('<html><script>')) : false,
      });
      return route.fulfill({ status: 200, headers: { etag: 'audit-etag' }, body: '' });
    }
    if (url.hostname === 'nominatim.openstreetmap.org') {
      if (url.pathname.includes('/search')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([{
            place_id: 101,
            licence: 'synthetic audit response',
            osm_type: 'node',
            osm_id: 101,
            lat: '-6.170100',
            lon: '106.831000',
            display_name: 'Synthetic Audit Location, Jakarta, Indonesia',
            class: 'place',
            type: 'monument',
            importance: 0.9,
            boundingbox: ['-6.171', '-6.169', '106.830', '106.832'],
          }]),
        });
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ address: { country_code: 'id', country: 'Indonesia' } }) });
    }
    if (/api\.mapbox\.com|tiles\.mapbox\.com|events\.mapbox\.com/.test(url.hostname)) {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) return route.fulfill({ status: 204, body: '' });
      if (url.pathname.includes('/styles/v1/')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: 8, sources: {}, layers: [] }) });
      if (url.pathname.endsWith('.pbf')) return route.fulfill({ status: 200, contentType: 'application/x-protobuf', body: Buffer.alloc(0) });
      if (/\.(png|jpg|webp)$/.test(url.pathname)) return route.fulfill({ status: 200, contentType: 'image/png', body: validPng });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ features: [] }) });
    }
    return route.continue();
  });

  const result = { scenario, cardId, startedAt: new Date().toISOString(), errors: [], consoleMessages, pageErrors, network, s3Uploads };
  try {
    await page.goto(`${appURL}/${cardId}/flood?lang=en`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(900);
    await clickTraining(page);
    await enableLocation(page);
    await setDepthAndNext(page);
    await photoAndDescription(page, scenario.uploadMode);
    await submitReview(page, scenario.doubleSubmit);
    result.finalURL = page.url();
    result.finalText = (await page.locator('body').innerText()).slice(0, 5000);
    result.reportPutCount = reportPutCount;
    result.reportPatchCount = reportPatchCount;
    result.abortedReport = abortedReport;
    result.cardAfter = await api('GET', `/cards/${cardId}`);
    result.reportPersisted = Boolean(result.cardAfter?.data?.result?.report);
    await page.screenshot({ path: path.join(outDir, `${scenario.id}.png`), fullPage: true });
  } catch (error) {
    result.errors.push({ message: String(error), stack: error?.stack });
    result.finalURL = page.url();
    result.finalText = await page.locator('body').innerText().catch(() => '');
    result.reportPutCount = reportPutCount;
    result.reportPatchCount = reportPatchCount;
    result.abortedReport = abortedReport;
    result.cardAfter = await api('GET', `/cards/${cardId}`).catch(error2 => ({ error: String(error2) }));
    result.reportPersisted = Boolean(result.cardAfter?.data?.result?.report);
    await page.screenshot({ path: path.join(outDir, `${scenario.id}-error.png`), fullPage: true }).catch(() => null);
  }
  result.s3Uploads = s3Uploads;
  result.network = network;
  fs.writeFileSync(path.join(outDir, `${scenario.id}.json`), JSON.stringify(result, null, 2));
  await context.close();
  return result;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const scenarios = [
    { id: 'full-success-no-image' },
    { id: 'double-submit', doubleSubmit: true },
    { id: 'network-drop', abortReport: true },
    { id: 'valid-image', uploadMode: 'valid' },
    { id: 'disguised-image', uploadMode: 'disguised' },
    { id: 'oversized-image', uploadMode: 'oversized' },
    { id: 'gps-exif-image', uploadMode: 'exif' },
  ];
  const results = [];
  try {
    for (const scenario of scenarios) results.push(await runScenario(browser, scenario));
  } finally {
    await browser.close();
  }
  const summary = {
    generatedAt: new Date().toISOString(),
    scenarioCount: results.length,
    scenarioResults: results.map(result => ({
      id: result.scenario.id,
      errors: result.errors.length,
      finalURL: result.finalURL,
      reportPutCount: result.reportPutCount,
      reportPatchCount: result.reportPatchCount,
      reportPersisted: result.reportPersisted,
      s3Uploads: result.s3Uploads,
      pageErrors: result.pageErrors,
    })),
  };
  save('reportcards-full-e2e-summary.json', summary);
  console.log(JSON.stringify(summary, null, 2));
  const base = results.find(result => result.scenario.id === 'full-success-no-image');
  if (!base || !base.reportPersisted || base.errors.length) process.exitCode = 2;
}

main().catch(error => {
  fs.writeFileSync(path.join(outDir, 'fatal-error.txt'), error?.stack || String(error));
  process.exitCode = 1;
});
