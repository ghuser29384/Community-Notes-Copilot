import { chromium, devices } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
import path from 'node:path';

const baseURL = process.env.REPORTCARDS_URL || 'http://127.0.0.1:4200';
const outDir = path.resolve(process.env.AUDIT_OUTPUT || 'artifacts/reportcards-browser');
fs.mkdirSync(outDir, { recursive: true });

const decks = ['flood', 'fire', 'haze', 'earthquake', 'wind', 'volcano', 'notifications', 'need', 'giver'];
const syntheticMarker = 'SITI-AUDIT-SYNTHETIC-NOT-A-REAL-DISASTER';
const xssMarker = `<img src=x onerror="window.__sitiAuditXss='executed'">${syntheticMarker}`;
const longText = `${syntheticMarker} ` + 'A'.repeat(5000) + ' 🌊🔥🌋 زلزال BENCANA';

const onePixelPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=',
  'base64'
);
const filesDir = path.join(outDir, 'synthetic-files');
fs.mkdirSync(filesDir, { recursive: true });
fs.writeFileSync(path.join(filesDir, 'valid.png'), onePixelPng);
fs.writeFileSync(path.join(filesDir, 'html-disguised-as-jpg.jpg'), '<html><script>window.top.__sitiAuditXss="file"</script></html>');
fs.writeFileSync(path.join(filesDir, 'oversized.jpg'), Buffer.alloc(12 * 1024 * 1024, 0x41));

function safeName(value) {
  return value.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 140);
}

function saveJSON(name, data) {
  fs.writeFileSync(path.join(outDir, name), JSON.stringify(data, null, 2));
}

function normalizeText(text) {
  return text.replace(/\s+/g, ' ').trim();
}

async function installRoutes(context, scenario) {
  const intercepted = [];
  let submitAttempts = 0;
  let abortedSubmit = false;

  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const isLocal = url.origin === new URL(baseURL).origin;
    const record = {
      url: request.url(), method, resourceType: request.resourceType(),
      postData: request.postData(), headers: request.headers(),
    };

    // Never allow a mutation request to escape the isolated local browser.
    if (!isLocal && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      intercepted.push({ ...record, action: 'blocked-external-mutation' });
      return route.fulfill({ status: 418, contentType: 'application/json', body: JSON.stringify({ audit: true, blocked: true }) });
    }

    if (/api\.petabencana\.id|data\.petabencana\.id/.test(url.hostname)) {
      intercepted.push({ ...record, action: 'mock-api' });
      if (['PUT', 'POST', 'PATCH'].includes(method)) {
        submitAttempts += 1;
        if (scenario.abortFirstSubmit && !abortedSubmit) {
          abortedSubmit = true;
          return route.abort('internetdisconnected');
        }
        await new Promise(resolve => setTimeout(resolve, scenario.submitDelayMs || 0));
        return route.fulfill({
          status: 200,
          headers: { 'access-control-allow-origin': '*' },
          contentType: 'application/json',
          body: JSON.stringify({
            statusCode: 200,
            result: { card_id: 'test123', report_id: 'audit-report-id', image_id: 'audit-image-id', success: true },
          }),
        });
      }
      if (/\/cards\/[^/]+\/images/.test(url.pathname)) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ statusCode: 200, result: { url: `${baseURL}/audit-upload-target` } }) });
      }
      if (/\/cards\//.test(url.pathname)) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            statusCode: 200,
            result: {
              card_id: 'test123',
              created_at: new Date().toISOString(),
              expires_at: new Date(Date.now() + 3600_000).toISOString(),
              source: 'audit',
            },
          }),
        });
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ statusCode: 200, result: [] }) });
    }

    if (url.pathname === '/audit-upload-target') {
      intercepted.push({ ...record, action: 'mock-upload' });
      return route.fulfill({ status: 200, body: '' });
    }

    if (/api\.mapbox\.com|tiles\.mapbox\.com|events\.mapbox\.com/.test(url.hostname)) {
      intercepted.push({ ...record, action: scenario.blockMap ? 'blocked-map' : 'mock-map' });
      if (scenario.blockMap) return route.abort('failed');
      if (url.pathname.endsWith('.pbf')) return route.fulfill({ status: 200, contentType: 'application/x-protobuf', body: Buffer.alloc(0) });
      if (/\.png|\.jpg|\.webp/.test(url.pathname)) return route.fulfill({ status: 200, contentType: 'image/png', body: onePixelPng });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ features: [] }) });
    }

    if (!isLocal && ['image', 'font', 'stylesheet'].includes(request.resourceType())) {
      intercepted.push({ ...record, action: 'allowed-static-external' });
      return route.continue();
    }
    return route.continue();
  });

  return {
    intercepted,
    get submitAttempts() { return submitAttempts; },
    get abortedSubmit() { return abortedSubmit; },
  };
}

async function axe(page, name) {
  try {
    const result = await new AxeBuilder({ page }).analyze();
    const violations = result.violations.map(v => ({
      id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl,
      nodes: v.nodes.map(n => ({ target: n.target, html: n.html, failureSummary: n.failureSummary })),
    }));
    saveJSON(`axe-${safeName(name)}.json`, violations);
    return { violationCount: violations.length, violations };
  } catch (error) {
    return { error: String(error) };
  }
}

async function snapshot(page) {
  return page.evaluate(() => ({
    url: location.href,
    title: document.title,
    lang: document.documentElement.lang,
    bodyText: document.body?.innerText?.slice(0, 16000) || '',
    bodyHTML: document.body?.innerHTML?.slice(0, 30000) || '',
    activeElement: document.activeElement?.outerHTML?.slice(0, 1000) || null,
    viewport: { width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight },
    buttons: [...document.querySelectorAll('button')].filter(el => el.offsetParent !== null).map(el => ({ text: el.innerText.trim(), disabled: el.disabled, type: el.getAttribute('type'), aria: el.getAttribute('aria-label') })).slice(0, 100),
    inputs: [...document.querySelectorAll('input, textarea, select')].filter(el => el.offsetParent !== null).map(el => ({ tag: el.tagName, type: el.getAttribute('type'), name: el.getAttribute('name'), placeholder: el.getAttribute('placeholder'), value: el.value, required: el.required, aria: el.getAttribute('aria-label') })).slice(0, 100),
    links: [...document.querySelectorAll('a')].filter(el => el.offsetParent !== null).map(el => ({ text: el.innerText.trim(), href: el.href })).slice(0, 100),
  }));
}

async function fillVisibleControls(page, mode = 'normal') {
  const actions = [];
  const inputs = page.locator('input:visible, textarea:visible, select:visible');
  const count = await inputs.count();
  for (let i = 0; i < count; i++) {
    const el = inputs.nth(i);
    const tag = await el.evaluate(node => node.tagName.toLowerCase());
    const type = (await el.getAttribute('type') || '').toLowerCase();
    const placeholder = (await el.getAttribute('placeholder') || '').toLowerCase();
    try {
      if (type === 'file') {
        await el.setInputFiles(path.join(filesDir, mode === 'invalid-file' ? 'html-disguised-as-jpg.jpg' : mode === 'oversized-file' ? 'oversized.jpg' : 'valid.png'));
        actions.push({ action: 'file', index: i, mode });
      } else if (type === 'checkbox' || type === 'radio') {
        if (!(await el.isChecked())) await el.check({ force: true });
        actions.push({ action: 'check', index: i });
      } else if (tag === 'select') {
        const options = await el.locator('option').evaluateAll(opts => opts.map(o => ({ value: o.value, text: o.textContent, disabled: o.disabled })));
        const option = options.find(o => !o.disabled && o.value !== '') || options.find(o => !o.disabled);
        if (option) await el.selectOption(option.value);
        actions.push({ action: 'select', index: i, value: option?.value });
      } else if (type !== 'hidden' && type !== 'submit' && type !== 'button') {
        let value = syntheticMarker;
        if (mode === 'xss') value = xssMarker;
        if (mode === 'long') value = longText;
        if (type === 'email') value = 'audit@example.invalid';
        if (type === 'tel' || placeholder.includes('phone') || placeholder.includes('telepon')) value = '+620000000000';
        if (type === 'number') value = placeholder.includes('depth') ? '50' : '1';
        if (type === 'date') value = '2030-01-01';
        if (type === 'time') value = '12:00';
        await el.fill(value);
        actions.push({ action: 'fill', index: i, type, valueLength: value.length });
      }
    } catch (error) {
      actions.push({ action: 'error', index: i, error: String(error) });
    }
  }
  return actions;
}

async function clickChoice(page) {
  const candidates = [
    page.locator('button:visible:not([disabled])').filter({ hasNotText: /next|back|submit|continue|previous|kembali|lanjut|kirim|review|close/i }),
    page.locator('[role="button"]:visible'),
    page.locator('.type:visible, .option:visible, .card:visible, .mat-radio-button:visible, .mat-checkbox:visible'),
  ];
  for (const group of candidates) {
    const count = await group.count().catch(() => 0);
    for (let i = 0; i < Math.min(count, 12); i++) {
      const candidate = group.nth(i);
      if (!(await candidate.isVisible().catch(() => false))) continue;
      const text = normalizeText(await candidate.innerText().catch(() => ''));
      if (/privacy|terms|language|menu|about/i.test(text)) continue;
      try {
        await candidate.click({ timeout: 1500 });
        return { clicked: true, text: text.slice(0, 200) };
      } catch { /* try next */ }
    }
  }
  return { clicked: false };
}

async function clickNextOrSubmit(page, doubleSubmit = false) {
  const patterns = [/next/i, /continue/i, /lanjut/i, /selanjutnya/i, /review/i, /submit/i, /kirim/i, /send/i, /donate/i, /offer/i];
  const buttons = page.locator('button:visible:not([disabled])');
  const count = await buttons.count();
  for (const pattern of patterns) {
    for (let i = 0; i < count; i++) {
      const button = buttons.nth(i);
      const text = normalizeText(await button.innerText().catch(() => ''));
      if (!pattern.test(text)) continue;
      try {
        if (doubleSubmit && /submit|kirim|send|donate|offer/i.test(text)) {
          await Promise.allSettled([button.click({ timeout: 2000 }), button.click({ timeout: 2000 })]);
        } else {
          await button.click({ timeout: 2500 });
        }
        return { clicked: true, text, submitLike: /submit|kirim|send|donate|offer/i.test(text) };
      } catch { /* try next */ }
    }
  }
  return { clicked: false };
}

async function advanceFlow(page, options = {}) {
  const steps = [];
  let lastURL = '';
  let stagnant = 0;
  for (let step = 0; step < (options.maxSteps || 18); step++) {
    await page.waitForTimeout(250);
    const before = await snapshot(page);
    const fillActions = await fillVisibleControls(page, options.inputMode || 'normal');
    const choice = await clickChoice(page);
    const navigation = await clickNextOrSubmit(page, options.doubleSubmit);
    await page.waitForTimeout(navigation.submitLike ? 1200 : 350);
    const after = await snapshot(page);
    const record = { step, before, fillActions, choice, navigation, after };
    steps.push(record);
    const successText = after.bodyText.toLowerCase();
    if (/thank|terima kasih|success|submitted|berhasil/.test(successText)) break;
    if (!choice.clicked && !navigation.clicked && fillActions.length === 0) break;
    if (after.url === lastURL && after.bodyText === before.bodyText) stagnant += 1; else stagnant = 0;
    if (stagnant >= 2) break;
    lastURL = after.url;
  }
  return steps;
}

async function runScenario(browser, scenario) {
  const contextOptions = scenario.device ? { ...devices[scenario.device] } : { viewport: scenario.viewport || { width: 1440, height: 1000 } };
  if (scenario.geolocation) {
    contextOptions.geolocation = scenario.geolocation;
    contextOptions.permissions = ['geolocation'];
  }
  const context = await browser.newContext(contextOptions);
  if (scenario.denyGeolocation) await context.clearPermissions();
  const network = await installRoutes(context, scenario);
  const page = await context.newPage();
  const consoleMessages = [];
  const pageErrors = [];
  page.on('console', msg => consoleMessages.push({ type: msg.type(), text: msg.text() }));
  page.on('pageerror', err => pageErrors.push(String(err)));
  const started = Date.now();
  const result = { scenario, startedAt: new Date().toISOString(), consoleMessages, pageErrors, steps: [], errors: [] };
  try {
    await page.goto(`${baseURL}/${scenario.cardId || 'test123'}/${scenario.deck}${scenario.query || ''}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(1200);
    result.initial = await snapshot(page);
    result.initialAxe = await axe(page, `${scenario.id}-initial`);
    await page.screenshot({ path: path.join(outDir, `${scenario.id}-initial.png`), fullPage: true });

    if (scenario.keyboardProbe) {
      await page.keyboard.press('Tab');
      const first = await snapshot(page);
      await page.keyboard.press('Enter');
      await page.waitForTimeout(250);
      result.keyboard = { afterFirstTab: first.activeElement, afterEnter: await snapshot(page) };
    }

    result.steps = await advanceFlow(page, scenario);
    result.final = await snapshot(page);
    result.finalAxe = await axe(page, `${scenario.id}-final`);
    result.xssExecuted = await page.evaluate(() => window.__sitiAuditXss || null);
    await page.screenshot({ path: path.join(outDir, `${scenario.id}-final.png`), fullPage: true });
  } catch (error) {
    result.errors.push({ error: String(error), stack: error?.stack });
    await page.screenshot({ path: path.join(outDir, `${scenario.id}-error.png`), fullPage: true }).catch(() => null);
  }
  result.durationMs = Date.now() - started;
  result.intercepted = network.intercepted;
  result.submitAttempts = network.submitAttempts;
  result.firstSubmitAborted = network.abortedSubmit;
  result.externalMutationEscaped = network.intercepted.some(x => x.action === 'blocked-external-mutation');
  saveJSON(`${scenario.id}.json`, result);
  await context.close();
  return result;
}

const scenarios = [];
for (const deck of decks) {
  scenarios.push({ id: `RC-${deck}-desktop-happy`, deck, geolocation: { latitude: -6.175392, longitude: 106.827153 }, maxSteps: 20 });
  scenarios.push({ id: `RC-${deck}-mobile-happy`, deck, device: 'iPhone 13', geolocation: { latitude: -6.175392, longitude: 106.827153 }, maxSteps: 20 });
}
scenarios.push(
  { id: 'RC-flood-id-language', deck: 'flood', query: '?lang=id', geolocation: { latitude: -6.175392, longitude: 106.827153 }, maxSteps: 20 },
  { id: 'RC-flood-en-language', deck: 'flood', query: '?lang=en', geolocation: { latitude: -6.175392, longitude: 106.827153 }, maxSteps: 20 },
  { id: 'RC-flood-geolocation-denied', deck: 'flood', denyGeolocation: true, maxSteps: 8 },
  { id: 'RC-flood-map-unavailable', deck: 'flood', blockMap: true, denyGeolocation: true, maxSteps: 8 },
  { id: 'RC-flood-xss-description', deck: 'flood', geolocation: { latitude: -6.175392, longitude: 106.827153 }, inputMode: 'xss', maxSteps: 20 },
  { id: 'RC-flood-long-unicode', deck: 'flood', geolocation: { latitude: -6.175392, longitude: 106.827153 }, inputMode: 'long', maxSteps: 20 },
  { id: 'RC-flood-invalid-image', deck: 'flood', geolocation: { latitude: -6.175392, longitude: 106.827153 }, inputMode: 'invalid-file', maxSteps: 20 },
  { id: 'RC-flood-oversized-image', deck: 'flood', geolocation: { latitude: -6.175392, longitude: 106.827153 }, inputMode: 'oversized-file', maxSteps: 20 },
  { id: 'RC-flood-submit-network-drop', deck: 'flood', geolocation: { latitude: -6.175392, longitude: 106.827153 }, abortFirstSubmit: true, maxSteps: 22 },
  { id: 'RC-flood-double-submit', deck: 'flood', geolocation: { latitude: -6.175392, longitude: 106.827153 }, doubleSubmit: true, submitDelayMs: 1000, maxSteps: 22 },
  { id: 'RC-flood-keyboard', deck: 'flood', keyboardProbe: true, geolocation: { latitude: -6.175392, longitude: 106.827153 }, maxSteps: 5 },
  { id: 'RC-invalid-card-short', deck: 'flood', cardId: 'x', geolocation: { latitude: -6.175392, longitude: 106.827153 }, maxSteps: 3 },
  { id: 'RC-invalid-card-long', deck: 'flood', cardId: 'A'.repeat(200), geolocation: { latitude: -6.175392, longitude: 106.827153 }, maxSteps: 3 },
  { id: 'RC-invalid-deck', deck: 'not-a-disaster', cardId: 'test123', maxSteps: 3 },
  { id: 'RC-direct-review-route', deck: 'flood/review', cardId: 'test123', geolocation: { latitude: -6.175392, longitude: 106.827153 }, maxSteps: 4 },
);

async function main() {
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const scenario of scenarios) {
      results.push(await runScenario(browser, scenario));
    }
  } finally {
    await browser.close();
  }
  const summary = {
    generatedAt: new Date().toISOString(),
    baseURL,
    scenarioCount: results.length,
    scenariosWithErrors: results.filter(x => x.errors.length).map(x => x.scenario.id),
    scenariosWithPageErrors: results.filter(x => x.pageErrors.length).map(x => x.scenario.id),
    scenariosThatSubmitted: results.filter(x => x.submitAttempts > 0).map(x => ({ id: x.scenario.id, attempts: x.submitAttempts })),
    doubleSubmitObservations: results.filter(x => x.scenario.doubleSubmit).map(x => ({ id: x.scenario.id, attempts: x.submitAttempts })),
    networkDropObservations: results.filter(x => x.scenario.abortFirstSubmit).map(x => ({ id: x.scenario.id, attempts: x.submitAttempts, aborted: x.firstSubmitAborted, finalText: x.final?.bodyText?.slice(0, 1000) })),
    xssExecution: results.filter(x => x.xssExecuted).map(x => ({ id: x.scenario.id, value: x.xssExecuted })),
    externalMutationEscaped: results.filter(x => x.externalMutationEscaped).map(x => x.scenario.id),
    axeViolationIds: [...new Set(results.flatMap(x => [x.initialAxe, x.finalAxe].flatMap(a => a?.violations || []).map(v => v.id)))],
  };
  saveJSON('reportcards-browser-summary.json', summary);
  console.log(JSON.stringify(summary, null, 2));
}

main().catch(error => {
  fs.writeFileSync(path.join(outDir, 'fatal-error.txt'), error?.stack || String(error));
  process.exitCode = 1;
});
