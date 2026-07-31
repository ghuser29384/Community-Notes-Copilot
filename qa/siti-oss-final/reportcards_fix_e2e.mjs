import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const appURL = (process.env.REPORTCARDS_URL || 'http://127.0.0.1:4200').replace(/\/$/, '');
const apiURL = (process.env.SITI_SERVER_URL || 'http://127.0.0.1:8001').replace(/\/$/, '');
const outDir = path.resolve(process.env.SITI_VALIDATION_OUT || 'artifacts/reportcards-fix-e2e');
fs.mkdirSync(outDir, { recursive: true });

const validPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=',
  'base64',
);
const validExifJpeg = Buffer.from(
  '/9j/4QBBRXhpZgAAU0lUSV9BVURJVF9HUFNMYXRpdHVkZT0tNi4xNzUzOTI7R1BTTG9uZ2l0dWRlPTEwNi44MjcxNTM7/+AAEEpGSUYAAQEAAAEAAQAA/9sAQwAFAwQEBAMFBAQEBQUFBgcMCAcHBwcPCwsJDBEPEhIRDxERExYcFxMUGhURERghGBodHR8fHxMXIiQiHiQcHh8e/9sAQwEFBQUHBgcOCAgOHhQRFB4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4e/8AAEQgAAgACAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/aAAwDAQACEQMRAD8A8sooor86P7LP/9k=',
  'base64',
);
const files = {
  valid: { name: 'valid.png', mimeType: 'image/png', buffer: validPng },
  disguised: {
    name: 'disguised.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from('<html><script>window.__siti_bad=1</script></html>'),
  },
  oversized: {
    name: 'oversized.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.alloc(12 * 1024 * 1024, 0x41),
  },
  exif: { name: 'gps-exif.jpg', mimeType: 'image/jpeg', buffer: validExifJpeg },
};

function save(name, value) {
  fs.writeFileSync(path.join(outDir, name), JSON.stringify(value, null, 2));
}

function nextButton(page) {
  return page.locator('button:visible').filter({ hasText: /^\s*NEXT\s*$/i }).first();
}

async function api(method, route, body) {
  const response = await fetch(apiURL + route, {
    method,
    headers: {
      'content-type': 'application/json',
      'user-agent': 'SitiOSS-Fix-E2E/2026-07-31',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data;
  try { data = await response.json(); } catch { data = await response.text(); }
  return { status: response.status, data };
}

async function createCard(label) {
  const result = await api('POST', '/cards', {
    username: `fix-e2e-${label}`,
    network: 'twitter',
    language: 'en',
    network_data: {},
  });
  if (result.status !== 200) throw new Error(`card creation failed: ${JSON.stringify(result)}`);
  return result.data.cardId;
}

async function clickTraining(page) {
  const button = page.getByRole('button', { name: /Complete Training Exercise/i });
  await button.waitFor({ state: 'visible', timeout: 15000 });
  await button.click();
}

async function selectLocation(page) {
  const search = page.locator('input[name=search]');
  await search.waitFor({ state: 'visible', timeout: 15000 });
  await search.fill('Monumen Nasional');
  const result = page.locator('.dynamic-search-results__result').first();
  await result.waitFor({ state: 'visible', timeout: 15000 });
  await result.click();
  const next = nextButton(page);
  await next.waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForTimeout(300);
  if (await next.isDisabled()) throw new Error('NEXT remained disabled after a concrete location search result was selected');
  await next.click();
}

async function setDepth(page) {
  await page.waitForURL(/\/depth(?:\?|$)/, { timeout: 15000 });
  const zone = page.locator('#sliderZone');
  await zone.waitFor({ state: 'visible', timeout: 15000 });
  const box = await zone.boundingBox();
  if (!box) throw new Error('depth slider has no bounding box');
  await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.35);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.25, { steps: 8 });
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
    await page.waitForTimeout(uploadMode === 'oversized' ? 1800 : 1000);
  }
  const imageError = await page.locator('[role=alert]').allInnerTexts().catch(() => []);
  await nextButton(page).click();
  await page.waitForURL(/\/description(?:\?|$)/, { timeout: 15000 });
  await page.locator('textarea[name=textbox]').fill(`SITI FIX E2E ${uploadMode || 'no-image'} ${new Date().toISOString()}`);
  await nextButton(page).click();
  return imageError;
}

async function submitReview(page, scenario) {
  await page.waitForURL(/\/review(?:\?|$)/, { timeout: 15000 });
  let submit = page.locator('app-submit-button button:visible').first();
  await submit.waitFor({ state: 'visible', timeout: 15000 });
  if (await submit.isDisabled()) throw new Error('review submit button is disabled');
  if (scenario.doubleSubmit) {
    await Promise.allSettled([
      submit.click({ noWaitAfter: true }),
      submit.click({ noWaitAfter: true }),
    ]);
  } else {
    await submit.click({ noWaitAfter: true });
  }
  await page.waitForTimeout(1800);
  const afterFirst = {
    url: page.url(),
    text: (await page.locator('body').innerText()).slice(0, 3000),
    alerts: await page.locator('[role=alert]').allInnerTexts().catch(() => []),
  };
  let retried = false;
  if (scenario.retryAfterFailure && /\/review(?:\?|$)/.test(page.url())) {
    submit = page.locator('app-submit-button button:visible').first();
    if (await submit.isVisible() && !(await submit.isDisabled())) {
      await submit.click({ noWaitAfter: true });
      retried = true;
      await page.waitForTimeout(1800);
    }
  }
  await page.waitForURL(/\/thank(?:\?|$)/, { timeout: 5000 }).catch(() => null);
  return {
    afterFirst,
    retried,
    final: {
      url: page.url(),
      text: (await page.locator('body').innerText()).slice(0, 3000),
      alerts: await page.locator('[role=alert]').allInnerTexts().catch(() => []),
    },
  };
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
  let acceptedThenLost = null;

  page.on('console', message => consoleMessages.push({ type: message.type(), text: message.text() }));
  page.on('pageerror', error => pageErrors.push(String(error)));
  page.on('request', request => {
    if (request.url().startsWith(apiURL)) network.push({ phase: 'request', method: request.method(), url: request.url(), postData: request.postData() });
  });
  page.on('response', async response => {
    if (response.url().startsWith(apiURL)) {
      let body = null;
      try { body = await response.clone().json(); } catch {}
      network.push({ phase: 'response', status: response.status(), url: response.url(), body });
    }
  });

  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    if (url.origin === apiURL && url.pathname === `/cards/${cardId}` && method === 'PUT') {
      reportPutCount += 1;
      if (scenario.acceptedThenLost && !abortedReport) {
        abortedReport = true;
        const response = await fetch(request.url(), {
          method: 'PUT',
          headers: { 'content-type': request.headers()['content-type'] || 'application/json' },
          body: request.postData() || undefined,
        });
        let body;
        try { body = await response.json(); } catch { body = await response.text(); }
        acceptedThenLost = { status: response.status, body };
        return route.abort('internetdisconnected');
      }
      if (scenario.abortBeforeServer && !abortedReport) {
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
        signedHeaders: new URL(request.url()).searchParams.get('X-Amz-SignedHeaders'),
        contentType: request.headers()['content-type'],
        bytes: bytes?.length || 0,
        containsAuditGPS: bytes ? bytes.includes(Buffer.from('SITI_AUDIT_GPSLatitude')) : false,
        containsHTMLScript: bytes ? bytes.includes(Buffer.from('<html><script>')) : false,
        prefixHex: bytes?.subarray(0, 80).toString('hex') || '',
      });
      return route.fulfill({ status: 200, headers: { etag: 'audit-etag' }, body: '' });
    }
    if (url.hostname === 'nominatim.openstreetmap.org') {
      if (url.pathname.includes('/search')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([{ place_id: 101, lat: '-6.170100', lon: '106.831000', display_name: 'Synthetic Audit Location, Jakarta, Indonesia', boundingbox: ['-6.171', '-6.169', '106.830', '106.832'] }]),
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

  const result = { scenario, cardId, errors: [], consoleMessages, pageErrors, network, s3Uploads };
  try {
    await page.goto(`${appURL}/${cardId}/flood?lang=en`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(900);
    await clickTraining(page);
    await selectLocation(page);
    await setDepth(page);
    result.imageErrors = await photoAndDescription(page, scenario.uploadMode);
    result.submitEvidence = await submitReview(page, scenario);
    result.finalURL = page.url();
    result.finalText = (await page.locator('body').innerText()).slice(0, 5000);
  } catch (error) {
    result.errors.push({ message: String(error), stack: error?.stack });
    result.finalURL = page.url();
    result.finalText = await page.locator('body').innerText().catch(() => '');
  }
  result.reportPutCount = reportPutCount;
  result.reportPatchCount = reportPatchCount;
  result.abortedReport = abortedReport;
  result.acceptedThenLost = acceptedThenLost;
  result.cardAfter = await api('GET', `/cards/${cardId}`).catch(error => ({ error: String(error) }));
  result.reportPersisted = Boolean(result.cardAfter?.data?.result?.report);
  result.reportImageURL = result.cardAfter?.data?.result?.report?.image_url || null;
  result.s3Uploads = s3Uploads;
  result.network = network;
  await page.screenshot({ path: path.join(outDir, `${scenario.id}${result.errors.length ? '-error' : ''}.png`), fullPage: true }).catch(() => null);
  save(`${scenario.id}.json`, result);
  await context.close();
  return result;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const scenarios = [
    { id: 'full-success-no-image' },
    { id: 'double-submit', doubleSubmit: true },
    { id: 'network-drop-before-server', abortBeforeServer: true, retryAfterFailure: true },
    { id: 'accepted-response-lost', acceptedThenLost: true, retryAfterFailure: true },
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
  const byId = Object.fromEntries(results.map(result => [result.scenario.id, result]));
  const assertions = {
    base_success: Boolean(byId['full-success-no-image']?.reportPersisted && byId['full-success-no-image']?.errors.length === 0),
    double_submit_one_put: byId['double-submit']?.reportPutCount === 1 && byId['double-submit']?.reportPersisted,
    network_drop_retry: Boolean(byId['network-drop-before-server']?.submitEvidence?.retried && byId['network-drop-before-server']?.reportPersisted),
    accepted_response_loss_reconciled: Boolean(byId['accepted-response-lost']?.acceptedThenLost?.status === 200 && byId['accepted-response-lost']?.reportPersisted),
    valid_image_persisted: Boolean(byId['valid-image']?.s3Uploads.length === 1 && /\.png$/.test(byId['valid-image']?.reportImageURL || '')),
    signed_content_type_bound: byId['valid-image']?.s3Uploads[0]?.signedHeaders?.includes('content-type') || false,
    disguised_image_blocked: byId['disguised-image']?.s3Uploads.length === 0,
    oversized_image_blocked: byId['oversized-image']?.s3Uploads.length === 0,
    exif_marker_removed: Boolean(byId['gps-exif-image']?.s3Uploads.length === 1 && !byId['gps-exif-image']?.s3Uploads[0]?.containsAuditGPS),
    no_thank_title_error: results.every(result => !result.consoleMessages.some(message => /reading 'title'/.test(message.text))),
  };
  const summary = {
    generatedAt: new Date().toISOString(),
    scenarioCount: results.length,
    assertions,
    scenarioResults: results.map(result => ({
      id: result.scenario.id,
      errors: result.errors.length,
      finalURL: result.finalURL,
      reportPutCount: result.reportPutCount,
      reportPatchCount: result.reportPatchCount,
      reportPersisted: result.reportPersisted,
      reportImageURL: result.reportImageURL,
      acceptedThenLost: result.acceptedThenLost,
      imageErrors: result.imageErrors,
      s3Uploads: result.s3Uploads,
      pageErrors: result.pageErrors,
    })),
  };
  save('reportcards-fix-e2e-summary.json', summary);
  console.log(JSON.stringify(summary, null, 2));
  if (Object.values(assertions).some(value => !value)) process.exitCode = 2;
}

main().catch(error => {
  fs.writeFileSync(path.join(outDir, 'fatal-error.txt'), error?.stack || String(error));
  process.exitCode = 1;
});
