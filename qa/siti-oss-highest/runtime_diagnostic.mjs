import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const appURL = (process.env.REPORTCARDS_URL || 'http://127.0.0.1:4200').replace(/\/$/, '');
const apiURL = (process.env.SITI_SERVER_URL || 'http://127.0.0.1:8001').replace(/\/$/, '');
const outDir = path.resolve(process.env.SITI_DIAGNOSTIC_OUT || 'artifacts/runtime-diagnostic');
fs.mkdirSync(outDir, { recursive: true });

async function api(method, route, body) {
  const response = await fetch(apiURL + route, {
    method,
    headers: { 'content-type': 'application/json', 'user-agent': 'SitiOSS-Runtime-Diagnostic/2026-08-04' },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data;
  try { data = await response.json(); } catch { data = await response.text(); }
  return { status: response.status, data };
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1365, height: 900 },
  geolocation: { latitude: -6.175392, longitude: 106.827153 },
  permissions: ['geolocation'],
});
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send('Runtime.enable');

const evidence = {
  generatedAt: new Date().toISOString(),
  pageErrors: [],
  cdpExceptions: [],
  consoleMessages: [],
  scripts: [],
  responses: [],
};

page.on('pageerror', error => {
  evidence.pageErrors.push({
    name: error?.name || null,
    message: error?.message || String(error),
    stack: error?.stack || null,
  });
});
page.on('console', message => {
  evidence.consoleMessages.push({
    type: message.type(),
    text: message.text(),
    location: message.location(),
  });
});
page.on('response', response => {
  const url = response.url();
  if (/\.(?:js|css)(?:\?|$)/.test(url)) {
    evidence.responses.push({ url, status: response.status(), headers: response.headers() });
  }
});
cdp.on('Runtime.exceptionThrown', event => evidence.cdpExceptions.push(event));
cdp.on('Debugger.scriptParsed', event => {
  if (event.url) evidence.scripts.push({ url: event.url, scriptId: event.scriptId, sourceMapURL: event.sourceMapURL || null });
});
await cdp.send('Debugger.enable');

const card = await api('POST', '/cards', {
  username: 'runtime-diagnostic',
  network: 'twitter',
  language: 'en',
  network_data: {},
});
if (card.status !== 200) throw new Error(`Card creation failed: ${JSON.stringify(card)}`);
const cardId = card.data.cardId;

await page.goto(`${appURL}/${cardId}/flood?lang=en`, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(1500);
evidence.finalURL = page.url();
evidence.title = await page.title();
evidence.bodyText = (await page.locator('body').innerText()).slice(0, 4000);
await page.screenshot({ path: path.join(outDir, 'runtime-diagnostic.png'), fullPage: true });
fs.writeFileSync(path.join(outDir, 'runtime-diagnostic.json'), JSON.stringify(evidence, null, 2));
console.log(JSON.stringify(evidence, null, 2));

await context.close();
await browser.close();
