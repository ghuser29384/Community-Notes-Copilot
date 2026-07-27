import { chromium } from 'playwright';
import fs from 'node:fs/promises';

const target = 'https://ai.szcat.org/chat/share?shareId=esavvfKO6VFbAYH5mnP9yhWR';
const question = '我今天在南山区捡到一只后腿完全不能动的流浪猫，现在应该先做什么？猫网能提供什么帮助？';
const out = 'artifacts/szcat-ai-browser-smoke';
await fs.mkdir(out, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1365, height: 900 }, locale: 'zh-CN' });
const page = await context.newPage();
const network = [];
page.on('request', req => {
  if (/api|chat|completion|share/i.test(req.url())) network.push({ type: 'request', method: req.method(), url: req.url(), postData: req.postData()?.slice(0, 5000) });
});
page.on('response', async res => {
  if (/api|chat|completion|share/i.test(res.url())) network.push({ type: 'response', status: res.status(), url: res.url(), contentType: res.headers()['content-type'] });
});
page.on('console', msg => network.push({ type: 'console', level: msg.type(), text: msg.text() }));
page.on('pageerror', err => network.push({ type: 'pageerror', text: String(err) }));

const timeline = [];
let error = null;
try {
  await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.waitForTimeout(5000);
  await page.screenshot({ path: `${out}/before.png`, fullPage: true });
  const before = await page.locator('body').innerText();
  const inventory = await page.evaluate(() => ({
    title: document.title,
    url: location.href,
    textareas: [...document.querySelectorAll('textarea')].map((e, i) => ({ i, visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length), placeholder: e.placeholder, aria: e.getAttribute('aria-label') })),
    inputs: [...document.querySelectorAll('input')].map((e, i) => ({ i, type: e.type, visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length), placeholder: e.placeholder, aria: e.getAttribute('aria-label') })),
    editables: [...document.querySelectorAll('[contenteditable=true]')].map((e, i) => ({ i, visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length), text: e.textContent?.slice(0, 100) })),
    buttons: [...document.querySelectorAll('button')].map((e, i) => ({ i, visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length), text: e.innerText?.slice(0, 100), title: e.title, aria: e.getAttribute('aria-label') })).filter(x => x.visible)
  }));
  await fs.writeFile(`${out}/inventory.json`, JSON.stringify({ before, inventory }, null, 2));

  const composer = page.locator('textarea:visible').last();
  if (!(await composer.count())) throw new Error('No visible textarea');
  await composer.fill(question);
  await composer.press('Enter');

  for (let second = 0; second <= 60; second += 2) {
    await page.waitForTimeout(second === 0 ? 1000 : 2000);
    const text = await page.locator('body').innerText().catch(() => '');
    const value = await composer.inputValue().catch(() => '');
    timeline.push({ second: second + 1, bodyLength: text.length, composerValue: value, bodyTail: text.slice(-2000) });
  }
  await page.screenshot({ path: `${out}/after.png`, fullPage: true });
  await fs.writeFile(`${out}/after.txt`, await page.locator('body').innerText());
} catch (e) {
  error = String(e?.stack || e);
  await page.screenshot({ path: `${out}/error.png`, fullPage: true }).catch(() => {});
  await fs.writeFile(`${out}/error-body.txt`, await page.locator('body').innerText().catch(() => ''));
}

await fs.writeFile(`${out}/debug.json`, JSON.stringify({ testedAt: new Date().toISOString(), target, question, error, timeline, network }, null, 2));
await browser.close();
if (error) process.exitCode = 1;
