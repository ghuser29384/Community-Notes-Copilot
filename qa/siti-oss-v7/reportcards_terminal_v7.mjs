import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const appURL = (process.env.REPORTCARDS_URL || 'http://127.0.0.1:4200').replace(/\/$/, '');
const apiURL = (process.env.SITI_SERVER_URL || 'http://127.0.0.1:8001').replace(/\/$/, '');
const outDir = path.resolve(process.env.SITI_VALIDATION_OUT || 'artifacts/reportcards-terminal-v7');
fs.mkdirSync(outDir, { recursive: true });

const validPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=',
  'base64',
);
const fakeExifJpeg = Buffer.concat([
  Buffer.from([0xff, 0xd8, 0xff, 0xe1, 0x00, 0x3c]),
  Buffer.from('Exif\u0000\u0000SITI_AUDIT_GPSLatitude=-6.175392;GPSLongitude=106.827153;', 'utf8'),
  Buffer.from([0xff, 0xd9]),
]);
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
  exif: { name: 'gps-exif.jpg', mimeType: 'image/jpeg', buffer: fakeExifJpeg },
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
      'user-agent': 'SitiOSS-Isolated-Terminal-E2E-v7/2026-07-30',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data;
  try {
    data = await response.json();
  } catch {
    data = await response.text();
  }
  return { status: response.status, data };
}

async function createCard(label) {
  const result = await api('POST', '/cards', {
    username: `e2e-v7-${label}`,
    network: 'twitter',
    language: 'en',
    network_data: {},
  });
  if (result.status !== 200) throw new Error(`card creation failed: ${JSON.stringify(result)}`);
  return result.data.cardId;
}

async function clickTraining(page) {
  const button = page.getByRole('button', { name: /Complete Training Exercise/i });
  await button.waitFor({ state: 'visible', timeout: 20_000 });
  await button.click();
  await page.waitForURL(/\/flood\/location(?:\?|$)/, { timeout: 20_000 });
}

async function activateLocation(page) {
  const marker = page.locator('.mapboxgl-marker').last();
  await marker.waitFor({ state: 'visible', timeout: 20_000 });
  await marker.scrollIntoViewIfNeeded();

  // First exercise the user-visible pointer path. Mapbox marker dragging can be
  // nondeterministic in headless software-WebGL, so the exact outcome is recorded.
  const box = await marker.boundingBox();
  let pointerAttempt = { attempted: false };
  if (box) {
    pointerAttempt = { attempted: true, before: await marker.getAttribute('style') };
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 - 80, { steps: 18 });
    await page.mouse.up();
    await page.waitForTimeout(500);
    pointerAttempt.after = await marker.getAttribute('style');
  }

  const next = nextButton(page);
  await next.waitFor({ state: 'visible', timeout: 15_000 });
  if (!(await next.isDisabled())) {
    await next.click();
    return { mode: 'pointer-drag', pointerAttempt };
  }

  // Deterministic component-level fallback: invoke the *same Mapbox Marker
  // dragend listener registered by the application. This does not patch app
  // state directly; it moves the real Marker instance and fires its event.
  const componentAttempt = await page.evaluate(() => {
    function collectCandidates(host) {
      const candidates = [];
      const ngApi = window.ng;
      for (const method of ['getComponent', 'getOwningComponent']) {
        try {
          if (ngApi && typeof ngApi[method] === 'function') {
            const value = ngApi[method](host);
            if (value) candidates.push(value);
          }
        } catch {}
      }
      for (const element of [host, host?.firstElementChild, document.querySelector('#mapid')]) {
        const context = element && element.__ngContext__;
        if (Array.isArray(context)) {
          for (const value of context) {
            if (value && typeof value === 'object') candidates.push(value);
          }
        }
      }
      return [...new Set(candidates)];
    }

    const host = document.querySelector('app-location-picker');
    const candidates = collectCandidates(host);
    const component = candidates.find(
      value => value && value.currentMarker && value.deckService && typeof value.checkIsUserAbleToContinue === 'function',
    );
    if (!component) {
      return {
        ok: false,
        reason: 'location component not found',
        candidateKeys: candidates.slice(0, 20).map(value => Object.keys(value).slice(0, 40)),
        windowNgKeys: window.ng ? Object.keys(window.ng) : [],
      };
    }

    const markerInstance = component.currentMarker;
    const before = markerInstance.getLngLat();
    const center = component.map.getCenter();
    const target = { lng: Number(before.lng) + 0.003, lat: Number(before.lat) + 0.002 };
    markerInstance.setLngLat([target.lng, target.lat]);
    let fired = false;
    if (typeof markerInstance.fire === 'function') {
      markerInstance.fire('dragend');
      fired = true;
    }
    try {
      if (window.ng && typeof window.ng.applyChanges === 'function') window.ng.applyChanges(component);
    } catch {}
    return {
      ok: fired,
      fired,
      before: { lng: before.lng, lat: before.lat },
      center: { lng: center.lng, lat: center.lat },
      target,
      deckLocation: component.deckService.location,
      markerKeys: Object.keys(markerInstance).slice(0, 80),
      componentKeys: Object.keys(component).slice(0, 80),
    };
  });

  await page.waitForTimeout(300);
  if (await next.isDisabled()) {
    const debug = await page.evaluate(() => ({
      body: document.body.innerText.slice(0, 4000),
      buttons: [...document.querySelectorAll('button')].map(button => ({
        text: button.textContent?.trim(),
        disabled: button.disabled,
        className: button.className,
      })),
      markers: [...document.querySelectorAll('.mapboxgl-marker')].map(element => ({
        style: element.getAttribute('style'),
        transform: getComputedStyle(element).transform,
      })),
    }));
    throw new Error(
      `NEXT remained disabled after real pointer and Marker.dragend paths: ${JSON.stringify({ pointerAttempt, componentAttempt, debug })}`,
    );
  }
  await next.click();
  return { mode: 'mapbox-marker-dragend-event', pointerAttempt, componentAttempt };
}

async function activateDepth(page) {
  await page.waitForURL(/\/depth(?:\?|$)/, { timeout: 20_000 });
  const zone = page.locator('#sliderZone');
  await zone.waitFor({ state: 'visible', timeout: 20_000 });
  await zone.scrollIntoViewIfNeeded();
  const box = await zone.boundingBox();
  let pointerAttempt = { attempted: false };
  if (box) {
    pointerAttempt = { attempted: true };
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2, Math.max(20, box.y + box.height / 2 - 45), { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(250);
  }
  const next = nextButton(page);
  if (!(await next.isDisabled())) {
    await next.click();
    return { mode: 'pointer-drag', pointerAttempt };
  }

  const componentAttempt = await page.evaluate(() => {
    function candidates(host) {
      const result = [];
      const ngApi = window.ng;
      for (const method of ['getComponent', 'getOwningComponent']) {
        try {
          if (ngApi && typeof ngApi[method] === 'function') {
            const value = ngApi[method](host);
            if (value) result.push(value);
          }
        } catch {}
      }
      const context = host && host.__ngContext__;
      if (Array.isArray(context)) {
        for (const value of context) if (value && typeof value === 'object') result.push(value);
      }
      return [...new Set(result)];
    }
    const host = document.querySelector('app-depth-slider');
    const component = candidates(host).find(
      value => value && typeof value.dragEnd === 'function' && value.deckService && 'currentY' in value,
    );
    if (!component) return { ok: false, reason: 'depth component not found' };
    component.currentY = 37;
    component.depthText = '74 cm';
    component.dragEnd({ type: 'audit-dragend' });
    try {
      if (window.ng && typeof window.ng.applyChanges === 'function') window.ng.applyChanges(component);
    } catch {}
    return {
      ok: true,
      currentY: component.currentY,
      depthText: component.depthText,
      storedDepth: component.deckService.getFloodDepth(),
    };
  });
  await page.waitForTimeout(250);
  if (await next.isDisabled()) throw new Error(`NEXT remained disabled after depth component dragEnd: ${JSON.stringify(componentAttempt)}`);
  await next.click();
  return { mode: 'depth-component-dragend', pointerAttempt, componentAttempt };
}

async function photoAndDescription(page, uploadMode) {
  await page.waitForURL(/\/photo(?:\?|$)/, { timeout: 20_000 });
  let signedURLResponse = null;
  if (uploadMode) {
    const responsePromise = page
      .waitForResponse(response => response.url().includes('/images'), { timeout: 15_000 })
      .catch(() => null);
    await page.locator('input[type=file]').setInputFiles(files[uploadMode]);
    signedURLResponse = await responsePromise;
    await page.waitForTimeout(uploadMode === 'oversized' ? 1_800 : 700);
  }
  const photoNext = nextButton(page);
  await photoNext.scrollIntoViewIfNeeded();
  await photoNext.click();
  await page.waitForURL(/\/description(?:\?|$)/, { timeout: 20_000 });
  await page.locator('textarea[name=textbox]').fill(
    `SITI E2E v7 ${uploadMode || 'no-image'} ${new Date().toISOString()}`,
  );
  const descriptionNext = nextButton(page);
  await descriptionNext.click();
  return {
    uploadMode: uploadMode || null,
    signedURLStatus: signedURLResponse ? signedURLResponse.status() : null,
  };
}

async function submitReview(page, doubleSubmit) {
  await page.waitForURL(/\/review(?:\?|$)/, { timeout: 20_000 });
  const submit = page.locator('app-submit-button button:visible').first();
  await submit.waitFor({ state: 'visible', timeout: 20_000 });
  await submit.scrollIntoViewIfNeeded();
  if (await submit.isDisabled()) {
    const state = await page.evaluate(() => ({ body: document.body.innerText.slice(0, 5000) }));
    throw new Error(`review submit button is disabled: ${JSON.stringify(state)}`);
  }
  if (doubleSubmit) {
    await Promise.allSettled([
      submit.click({ noWaitAfter: true }),
      submit.click({ noWaitAfter: true }),
    ]);
  } else {
    await submit.click({ noWaitAfter: true });
  }
  await page.waitForURL(/\/(thank|error)(?:\?|$)/, { timeout: 20_000 }).catch(() => null);
  await page.waitForTimeout(1_200);
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
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ address: { country_code: 'id', country: 'Indonesia' } }),
      });
    }
    if (/api\.mapbox\.com|tiles\.mapbox\.com|events\.mapbox\.com/.test(url.hostname)) {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) return route.fulfill({ status: 204, body: '' });
      if (url.pathname.includes('/styles/v1/')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ version: 8, sources: {}, layers: [] }),
        });
      }
      if (url.pathname.endsWith('.pbf')) {
        return route.fulfill({ status: 200, contentType: 'application/x-protobuf', body: Buffer.alloc(0) });
      }
      if (/\.(png|jpg|webp)$/.test(url.pathname)) {
        return route.fulfill({ status: 200, contentType: 'image/png', body: validPng });
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ features: [] }) });
    }
    return route.continue();
  });

  const result = {
    scenario,
    cardId,
    startedAt: new Date().toISOString(),
    errors: [],
    consoleMessages,
    pageErrors,
    network,
    s3Uploads,
  };
  try {
    await page.goto(`${appURL}/${cardId}/flood?lang=en`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.waitForTimeout(800);
    await clickTraining(page);
    result.locationActivation = await activateLocation(page);
    result.depthActivation = await activateDepth(page);
    result.photo = await photoAndDescription(page, scenario.uploadMode);
    await submitReview(page, scenario.doubleSubmit);
  } catch (error) {
    result.errors.push({ message: String(error), stack: error?.stack });
  }

  result.finalURL = page.url();
  result.finalText = await page.locator('body').innerText().catch(() => '');
  result.reportPutCount = reportPutCount;
  result.reportPatchCount = reportPatchCount;
  result.abortedReport = abortedReport;
  result.cardAfter = await api('GET', `/cards/${cardId}`).catch(error => ({ error: String(error) }));
  result.reportPersisted = Boolean(result.cardAfter?.data?.result?.report);
  result.s3Uploads = s3Uploads;
  result.network = network;
  await page.screenshot({
    path: path.join(outDir, `${scenario.id}${result.errors.length ? '-error' : ''}.png`),
    fullPage: true,
  }).catch(() => null);
  save(`${scenario.id}.json`, result);
  await context.close();
  return result;
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--enable-unsafe-swiftshader'],
  });
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
    scope: 'isolated exact public Siti OSS components plus labelled audit-only compatibility migration; no production writes',
    scenarioCount: results.length,
    scenarioResults: results.map(result => ({
      id: result.scenario.id,
      errors: result.errors.length,
      finalURL: result.finalURL,
      locationMode: result.locationActivation?.mode || null,
      depthMode: result.depthActivation?.mode || null,
      reportPutCount: result.reportPutCount,
      reportPatchCount: result.reportPatchCount,
      abortedReport: result.abortedReport,
      reportPersisted: result.reportPersisted,
      s3Uploads: result.s3Uploads,
      pageErrors: result.pageErrors,
    })),
  };
  save('reportcards-terminal-v7-summary.json', summary);
  console.log(JSON.stringify(summary, null, 2));

  const base = results.find(result => result.scenario.id === 'full-success-no-image');
  if (!base || base.errors.length || !base.reportPersisted || base.reportPutCount !== 1) {
    process.exitCode = 2;
  }
}

main().catch(error => {
  fs.writeFileSync(path.join(outDir, 'fatal-error.txt'), error?.stack || String(error));
  process.exitCode = 1;
});
