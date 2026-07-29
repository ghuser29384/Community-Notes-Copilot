import { chromium, devices } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
import path from 'node:path';

const outDir = path.resolve(process.env.AUDIT_OUTPUT || 'artifacts/live-map-browser');
fs.mkdirSync(outDir, { recursive: true });
const sites = [
  { id: 'id', origin: 'https://petabencana.id', languages: ['en', 'id'] },
  { id: 'ph', origin: 'https://mapakalamidad.ph', languages: ['en'] },
];

function safe(value) { return value.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 160); }
function saveJSON(name, value) { fs.writeFileSync(path.join(outDir, name), JSON.stringify(value, null, 2)); }

async function runAxe(page, name) {
  try {
    const report = await new AxeBuilder({ page }).analyze();
    const violations = report.violations.map(v => ({
      id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl,
      nodes: v.nodes.map(n => ({ target: n.target, html: n.html, failureSummary: n.failureSummary })),
    }));
    saveJSON(`axe-${safe(name)}.json`, violations);
    return { violationCount: violations.length, violations };
  } catch (error) {
    return { error: String(error) };
  }
}

async function inspect(page) {
  return page.evaluate(() => {
    const visible = el => {
      const s = getComputedStyle(el); const r = el.getBoundingClientRect();
      return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
    };
    const text = document.body?.innerText || '';
    const reportLike = [...document.querySelectorAll('*')].filter(el => visible(el) && /report|laporan|ulat|bencana|flood|banjir|earthquake|gempa/i.test(el.textContent || ''));
    return {
      url: location.href,
      title: document.title,
      lang: document.documentElement.lang,
      bodyText: text.slice(0, 30000),
      bodyHTML: document.body?.innerHTML?.slice(0, 50000) || '',
      viewport: { width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight },
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
      mapCanvases: document.querySelectorAll('canvas').length,
      mapContainers: [...document.querySelectorAll('[class*="map"], [id*="map"]')].filter(visible).length,
      visibleButtons: [...document.querySelectorAll('button,[role="button"]')].filter(visible).map(el => ({ text: (el.textContent || '').trim(), aria: el.getAttribute('aria-label'), title: el.getAttribute('title'), tag: el.tagName })).slice(0, 200),
      visibleLinks: [...document.querySelectorAll('a')].filter(visible).map(el => ({ text: (el.textContent || '').trim(), href: el.href, aria: el.getAttribute('aria-label') })).slice(0, 200),
      headings: [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(visible).map(el => ({ level: el.tagName, text: (el.textContent || '').trim() })).slice(0, 100),
      reportLikeElementCount: reportLike.length,
      containsStatusWords: /verified|unverified|confirmed|terverifikasi|dikonfirmasi|timestamp|updated|diperbarui|ago|minutes|jam|menit/i.test(text),
      containsListAlternative: /list view|daftar|list of reports|laporan terkini|recent reports/i.test(text),
      containsLegend: /legend|legenda|water level|ketinggian|alert level|tingkat/i.test(text),
      containsPrivacyTerms: /privacy|privasi|terms|ketentuan/i.test(text),
      activeElement: document.activeElement?.outerHTML?.slice(0, 1000) || null,
    };
  });
}

async function installSafetyRoutes(context, scenario) {
  const network = [];
  let escapedMutation = false;
  await context.route('**/*', async route => {
    const req = route.request();
    const url = req.url();
    const method = req.method();
    const record = { url, method, type: req.resourceType(), postData: req.postData() };
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      escapedMutation = true;
      network.push({ ...record, action: 'blocked-mutation' });
      return route.fulfill({ status: 418, contentType: 'application/json', body: '{"audit":"mutation blocked"}' });
    }
    if (scenario.blockAPI && /api\.petabencana\.id|data\.petabencana\.id/.test(url)) {
      network.push({ ...record, action: 'blocked-api' });
      return route.abort('failed');
    }
    if (scenario.slowAPI && /api\.petabencana\.id|data\.petabencana\.id/.test(url)) {
      network.push({ ...record, action: 'slow-api' });
      await new Promise(resolve => setTimeout(resolve, 5000));
      return route.continue();
    }
    if (scenario.blockTiles && /mapbox|tile|tiles|pbf/.test(url)) {
      network.push({ ...record, action: 'blocked-tile' });
      return route.abort('failed');
    }
    network.push({ ...record, action: 'continue' });
    return route.continue();
  });
  return { network, get escapedMutation() { return escapedMutation; } };
}

async function exerciseKeyboard(page) {
  const states = [];
  for (let i = 0; i < 20; i++) {
    await page.keyboard.press('Tab');
    states.push(await page.evaluate(() => ({
      tag: document.activeElement?.tagName,
      text: (document.activeElement?.textContent || '').trim().slice(0, 200),
      aria: document.activeElement?.getAttribute('aria-label'),
      href: document.activeElement?.getAttribute('href'),
      className: document.activeElement?.className,
    })));
  }
  return states;
}

async function scenarioRun(browser, scenario) {
  const contextOptions = scenario.device ? { ...devices[scenario.device] } : { viewport: scenario.viewport || { width: 1440, height: 1000 } };
  const context = await browser.newContext(contextOptions);
  const safety = await installSafetyRoutes(context, scenario);
  const page = await context.newPage();
  const consoleMessages = [];
  const pageErrors = [];
  page.on('console', msg => consoleMessages.push({ type: msg.type(), text: msg.text() }));
  page.on('pageerror', err => pageErrors.push(String(err)));
  const result = { scenario, consoleMessages, pageErrors, errors: [], startedAt: new Date().toISOString() };
  const started = Date.now();
  try {
    const response = await page.goto(scenario.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    result.status = response?.status() ?? null;
    await page.waitForTimeout(scenario.slowAPI ? 7000 : 3500);
    result.initial = await inspect(page);
    result.axe = await runAxe(page, scenario.id);
    result.keyboard = await exerciseKeyboard(page);
    result.afterKeyboard = await inspect(page);
    await page.screenshot({ path: path.join(outDir, `${scenario.id}.png`), fullPage: true });

    if (scenario.offlineAfterLoad) {
      await context.setOffline(true);
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 }).catch(error => { result.offlineReloadError = String(error); });
      await page.waitForTimeout(1000);
      result.offline = await inspect(page).catch(error => ({ error: String(error) }));
      await page.screenshot({ path: path.join(outDir, `${scenario.id}-offline.png`), fullPage: true }).catch(() => null);
    }
  } catch (error) {
    result.errors.push({ error: String(error), stack: error?.stack });
    await page.screenshot({ path: path.join(outDir, `${scenario.id}-error.png`), fullPage: true }).catch(() => null);
  }
  result.durationMs = Date.now() - started;
  result.network = safety.network;
  result.mutationAttemptBlocked = safety.escapedMutation;
  saveJSON(`${scenario.id}.json`, result);
  await context.close();
  return result;
}

const scenarios = [];
for (const site of sites) {
  scenarios.push(
    { id: `${site.id}-home-desktop`, url: `${site.origin}/` },
    { id: `${site.id}-home-mobile`, url: `${site.origin}/`, device: 'iPhone 13' },
    { id: `${site.id}-map-desktop`, url: `${site.origin}/map` },
    { id: `${site.id}-map-mobile`, url: `${site.origin}/map`, device: 'iPhone 13' },
    { id: `${site.id}-map-api-failure`, url: `${site.origin}/map`, blockAPI: true },
    { id: `${site.id}-map-slow-api`, url: `${site.origin}/map`, slowAPI: true },
    { id: `${site.id}-map-no-tiles`, url: `${site.origin}/map`, blockTiles: true },
    { id: `${site.id}-offline-reload`, url: `${site.origin}/map`, offlineAfterLoad: true, device: 'iPhone 13' },
    { id: `${site.id}-invalid-city`, url: `${site.origin}/map/not-a-real-city` },
    { id: `${site.id}-invalid-report`, url: `${site.origin}/map/jakarta/not-a-real-report-id` },
    { id: `${site.id}-terms-privacy`, url: `${site.origin}/map?terms=p_p` },
    { id: `${site.id}-info-tab`, url: `${site.origin}/map?tab=info` },
    { id: `${site.id}-report-tab`, url: `${site.origin}/map?tab=report` },
  );
  for (const lang of site.languages) {
    scenarios.push({ id: `${site.id}-lang-${lang}`, url: `${site.origin}/map?lang=${lang}` });
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const scenario of scenarios) results.push(await scenarioRun(browser, scenario));
  } finally {
    await browser.close();
  }
  const summary = {
    generatedAt: new Date().toISOString(),
    scenarioCount: results.length,
    statusCounts: results.reduce((acc, r) => { const k = String(r.status); acc[k] = (acc[k] || 0) + 1; return acc; }, {}),
    scenarioErrors: results.filter(r => r.errors.length).map(r => ({ id: r.scenario.id, errors: r.errors })),
    pageErrors: results.filter(r => r.pageErrors.length).map(r => ({ id: r.scenario.id, errors: r.pageErrors })),
    consoleErrorCounts: results.map(r => ({ id: r.scenario.id, errors: r.consoleMessages.filter(x => x.type === 'error').length, warnings: r.consoleMessages.filter(x => x.type === 'warning' || x.type === 'warn').length })),
    horizontalOverflow: results.filter(r => r.initial?.horizontalOverflow).map(r => r.scenario.id),
    missingListAlternative: results.filter(r => r.initial && !r.initial.containsListAlternative).map(r => r.scenario.id),
    missingStatusWords: results.filter(r => r.initial && !r.initial.containsStatusWords).map(r => r.scenario.id),
    mutationAttemptsBlocked: results.filter(r => r.mutationAttemptBlocked).map(r => r.scenario.id),
    axeRuleIds: [...new Set(results.flatMap(r => (r.axe?.violations || []).map(v => v.id)))],
  };
  saveJSON('live-map-browser-summary.json', summary);
  console.log(JSON.stringify(summary, null, 2));
}

main().catch(error => {
  fs.writeFileSync(path.join(outDir, 'fatal-error.txt'), error?.stack || String(error));
  process.exitCode = 1;
});
