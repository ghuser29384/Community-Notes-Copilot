import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const outDir = path.resolve(process.env.AUDIT_OUTPUT || 'artifacts/live-map-interactions');
fs.mkdirSync(outDir, { recursive: true });
const origin = 'https://petabencana.id';

function save(name, data) { fs.writeFileSync(path.join(outDir, name), JSON.stringify(data, null, 2)); }
function norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); }

async function installReadOnlyGuard(context) {
  const blocked = [];
  await context.route('**/*', route => {
    const req = route.request();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method())) {
      blocked.push({ url: req.url(), method: req.method(), postData: req.postData() });
      return route.fulfill({ status: 418, contentType: 'application/json', body: '{"audit":"blocked"}' });
    }
    return route.continue();
  });
  return blocked;
}

async function visibleText(page) {
  return page.locator('body').innerText().then(norm).catch(() => '');
}

async function rootDwell(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const blocked = await installReadOnlyGuard(context);
  const page = await context.newPage();
  const consoleMessages = [];
  page.on('console', m => consoleMessages.push({ type: m.type(), text: m.text() }));
  const result = { checkpoints: [], blocked, consoleMessages };
  const response = await page.goto(`${origin}/`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  result.status = response?.status();
  let elapsed = 0;
  for (const delta of [1000, 4000, 10000, 15000, 30000]) {
    await page.waitForTimeout(delta);
    elapsed += delta;
    const text = await visibleText(page);
    result.checkpoints.push({
      elapsedMs: elapsed,
      url: page.url(),
      title: await page.title(),
      text: text.slice(0, 5000),
      visibleButtons: await page.locator('button:visible').allTextContents().then(x => x.map(norm)),
    });
    await page.screenshot({ path: path.join(outDir, `root-${elapsed}.png`), fullPage: true });
  }
  save('root-dwell.json', result);
  await context.close();
  return result;
}

async function interactionRun(browser, mobile = false) {
  const context = await browser.newContext(mobile ? { ...devices['iPhone 13'] } : { viewport: { width: 1440, height: 1000 } });
  const blocked = await installReadOnlyGuard(context);
  const page = await context.newPage();
  const consoleMessages = [];
  const pageErrors = [];
  page.on('console', m => consoleMessages.push({ type: m.type(), text: m.text() }));
  page.on('pageerror', e => pageErrors.push(String(e)));
  const id = mobile ? 'mobile' : 'desktop';
  const result = { id, blocked, consoleMessages, pageErrors, actions: [], errors: [] };
  try {
    await page.goto(`${origin}/map`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(4500);
    result.initial = {
      url: page.url(), text: (await visibleText(page)).slice(0, 10000),
      buttons: await page.locator('button:visible').allTextContents().then(x => x.map(norm)),
      htmlLang: await page.locator('html').getAttribute('lang'),
    };
    await page.screenshot({ path: path.join(outDir, `${id}-initial.png`), fullPage: true });

    // Open active-report list if available.
    const activeButton = page.getByRole('button', { name: /active reports|laporan aktif|report/i }).filter({ hasText: /\d/ }).first();
    if (await activeButton.count() && await activeButton.isVisible().catch(() => false)) {
      await activeButton.click();
      await page.waitForTimeout(500);
      result.actions.push({ action: 'open-active-reports', text: norm(await activeButton.innerText()), resultText: (await visibleText(page)).slice(0, 12000) });
      await page.screenshot({ path: path.join(outDir, `${id}-active-reports.png`), fullPage: true });
    } else {
      result.actions.push({ action: 'open-active-reports', found: false });
    }

    // Click visible map-marker candidates, record first usable detail panel.
    const candidates = page.locator('button:visible, [role="button"]:visible, img:visible, div:visible');
    const count = Math.min(await candidates.count(), 500);
    let clickedMarker = false;
    for (let i = 0; i < count; i++) {
      const el = candidates.nth(i);
      const box = await el.boundingBox().catch(() => null);
      if (!box || box.width > 130 || box.height > 130 || box.width < 12 || box.height < 12) continue;
      const text = norm(await el.innerText().catch(() => ''));
      const aria = await el.getAttribute('aria-label');
      const cls = String(await el.getAttribute('class') || '');
      if (!/(marker|cluster|report|incident|leaflet)/i.test(`${cls} ${aria || ''}`) && !/^\d{1,3}$/.test(text)) continue;
      try {
        await el.click({ timeout: 1500 });
        await page.waitForTimeout(500);
        const after = await visibleText(page);
        result.actions.push({ action: 'click-marker-candidate', index: i, text, aria, className: cls.slice(0, 500), resultText: after.slice(0, 14000) });
        await page.screenshot({ path: path.join(outDir, `${id}-marker-detail.png`), fullPage: true });
        clickedMarker = true;
        break;
      } catch { /* next */ }
    }
    if (!clickedMarker) result.actions.push({ action: 'click-marker-candidate', found: false });

    // Language toggles: verify actual content changes and html lang updates.
    for (const lang of ['EN', 'ID']) {
      const button = page.getByRole('button', { name: new RegExp(`^${lang}$`, 'i') }).first();
      if (await button.count() && await button.isVisible().catch(() => false)) {
        await button.click();
        await page.waitForTimeout(500);
        result.actions.push({ action: `language-${lang}`, text: (await visibleText(page)).slice(0, 8000), htmlLang: await page.locator('html').getAttribute('lang') });
      }
    }

    // Reporting call-to-action: record destination/UI, but read-only guard blocks mutations.
    const reportButton = page.getByRole('button', { name: /kirim laporan|send report|report/i }).last();
    if (await reportButton.count() && await reportButton.isVisible().catch(() => false)) {
      const beforeURL = page.url();
      await reportButton.click().catch(() => null);
      await page.waitForTimeout(1000);
      result.actions.push({ action: 'report-cta', beforeURL, afterURL: page.url(), text: (await visibleText(page)).slice(0, 10000) });
      await page.screenshot({ path: path.join(outDir, `${id}-report-cta.png`), fullPage: true });
    }
  } catch (error) {
    result.errors.push({ error: String(error), stack: error?.stack });
  }
  save(`${id}-interactions.json`, result);
  await context.close();
  return result;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  try {
    const root = await rootDwell(browser);
    const desktop = await interactionRun(browser, false);
    const mobile = await interactionRun(browser, true);
    save('interaction-summary.json', {
      generatedAt: new Date().toISOString(),
      rootLoadedAt: root.checkpoints.find(x => x.buttons.length > 0)?.elapsedMs || null,
      rootFinalText: root.checkpoints.at(-1)?.text,
      desktopActionCount: desktop.actions.length,
      mobileActionCount: mobile.actions.length,
      blockedMutationCount: desktop.blocked.length + mobile.blocked.length + root.blocked.length,
    });
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  fs.writeFileSync(path.join(outDir, 'fatal-error.txt'), error?.stack || String(error));
  process.exitCode = 1;
});
