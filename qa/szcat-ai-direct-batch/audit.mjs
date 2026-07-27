import fs from 'node:fs/promises';
import crypto from 'node:crypto';

const BASE = 'https://ai.szcat.org';
const SHARE_ID = 'esavvfKO6VFbAYH5mnP9yhWR';
const OUT = 'artifacts/szcat-ai-direct-batch';
const cases = JSON.parse(await fs.readFile(new URL('./cases.json', import.meta.url), 'utf8'));
await fs.mkdir(OUT, { recursive: true });

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const randomId = (n = 24) => crypto.randomBytes(Math.ceil(n * 0.75)).toString('base64url').slice(0, n);

function collectSetCookies(headers) {
  if (typeof headers.getSetCookie === 'function') return headers.getSetCookie();
  const value = headers.get('set-cookie');
  return value ? [value] : [];
}

function mergeCookies(jar, setCookies) {
  for (const raw of setCookies) {
    const first = raw.split(';', 1)[0];
    const eq = first.indexOf('=');
    if (eq > 0) jar.set(first.slice(0, eq).trim(), first.slice(eq + 1).trim());
  }
}

function cookieHeader(jar) {
  return [...jar.entries()].map(([k, v]) => `${k}=${v}`).join('; ');
}

function formatCurrentTime() {
  const d = new Date();
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    weekday: 'long'
  }).formatToParts(d);
  const get = type => parts.find(p => p.type === type)?.value || '';
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')} ${get('weekday')}`;
}

function extractStreamAnswer(text) {
  const chunks = [];
  const parsedEvents = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.startsWith('data:')) continue;
    const data = line.slice(5).trim();
    if (!data || data === '[DONE]') continue;
    try {
      const obj = JSON.parse(data);
      parsedEvents.push(obj);
      for (const choice of obj.choices || []) {
        const value = choice?.delta?.content ?? choice?.message?.content ?? choice?.text;
        if (typeof value === 'string') chunks.push(value);
      }
      const candidates = [obj.answer, obj.content, obj.text, obj?.data?.answer, obj?.data?.content];
      for (const candidate of candidates) if (typeof candidate === 'string') chunks.push(candidate);
    } catch {
      // Some FastGPT event payloads are raw text.
      if (!/^event:/i.test(data)) chunks.push(data);
    }
  }
  return { answer: chunks.join('').trim(), parsedEvents };
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 120_000) {
  return fetch(url, { ...options, signal: AbortSignal.timeout(timeoutMs) });
}

async function runCase(test, index) {
  const jar = new Map();
  const outLinkUid = `shareChat-${Date.now()}-${randomId(24)}`;
  const chatId = randomId(24);
  const requestId = randomId(24);
  const responseId = randomId(24);
  const started = Date.now();
  const trace = [];
  let appId = null;

  const commonHeaders = {
    'accept': 'application/json, text/event-stream, */*',
    'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'origin': BASE,
    'referer': `${BASE}/chat/share?shareId=${SHARE_ID}`,
    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36 SZCat-Audit/1.0'
  };

  try {
    const pageRes = await fetchWithTimeout(`${BASE}/chat/share?shareId=${SHARE_ID}`, { headers: commonHeaders }, 60_000);
    mergeCookies(jar, collectSetCookies(pageRes.headers));
    trace.push({ step: 'page', status: pageRes.status, contentType: pageRes.headers.get('content-type') });
    await pageRes.arrayBuffer();

    const initUrl = new URL(`${BASE}/api/core/chat/outLink/init`);
    initUrl.searchParams.set('chatId', chatId);
    initUrl.searchParams.set('shareId', SHARE_ID);
    initUrl.searchParams.set('outLinkUid', outLinkUid);
    const initRes = await fetchWithTimeout(initUrl, {
      headers: { ...commonHeaders, cookie: cookieHeader(jar) }
    }, 60_000);
    mergeCookies(jar, collectSetCookies(initRes.headers));
    const initText = await initRes.text();
    let initJson = null;
    try { initJson = JSON.parse(initText); } catch {}
    appId = initJson?.data?.appId || initJson?.data?._id || initJson?.data?.app?._id || null;
    trace.push({ step: 'init', status: initRes.status, body: initText.slice(0, 5000), cookies: [...jar.keys()], appId });
    if (!initRes.ok) throw new Error(`outLink init failed: ${initRes.status} ${initText.slice(0, 500)}`);

    const body = {
      messages: [{ dataId: requestId, hideInUI: false, role: 'user', content: test.q }],
      variables: { cTime: formatCurrentTime() },
      responseChatItemId: responseId,
      chatId,
      shareId: SHARE_ID,
      outLinkUid,
      retainDatasetCite: true,
      showSkillReferences: false,
      detail: true,
      stream: true
    };
    const chatRes = await fetchWithTimeout(`${BASE}/api/v2/chat/completions`, {
      method: 'POST',
      headers: {
        ...commonHeaders,
        cookie: cookieHeader(jar),
        'content-type': 'application/json'
      },
      body: JSON.stringify(body)
    }, 150_000);
    mergeCookies(jar, collectSetCookies(chatRes.headers));
    const raw = await chatRes.text();
    const parsed = extractStreamAnswer(raw);
    trace.push({ step: 'chat', status: chatRes.status, contentType: chatRes.headers.get('content-type'), rawChars: raw.length, rawHead: raw.slice(0, 5000) });

    let answer = parsed.answer;
    let records = null;
    if (!answer && appId) {
      await sleep(1200);
      const recordRes = await fetchWithTimeout(`${BASE}/api/core/chat/record/getRecords_v2`, {
        method: 'POST',
        headers: { ...commonHeaders, cookie: cookieHeader(jar), 'content-type': 'application/json' },
        body: JSON.stringify({ initialId: '', pageSize: 10, appId, shareId: SHARE_ID, outLinkUid, chatId, type: 'outLink' })
      }, 60_000);
      const recordText = await recordRes.text();
      try { records = JSON.parse(recordText); } catch { records = recordText; }
      trace.push({ step: 'records', status: recordRes.status, body: recordText.slice(0, 10000) });
      const list = records?.data?.list || records?.data || records?.list || [];
      const flat = Array.isArray(list) ? list : [];
      for (const item of flat) {
        const candidates = [item?.value, item?.content, item?.text, item?.answer, item?.data?.content];
        for (const candidate of candidates) {
          if (typeof candidate === 'string' && candidate.length > answer.length && candidate !== test.q) answer = candidate;
        }
      }
    }

    return {
      ...test,
      index,
      status: chatRes.ok && answer ? 'ok' : chatRes.ok ? 'empty' : 'http_error',
      httpStatus: chatRes.status,
      durationSeconds: Math.round((Date.now() - started) / 100) / 10,
      appId,
      chatId,
      outLinkUid,
      answer,
      raw,
      parsedEventCount: parsed.parsedEvents.length,
      records,
      trace,
      error: null
    };
  } catch (error) {
    return {
      ...test,
      index,
      status: 'error',
      durationSeconds: Math.round((Date.now() - started) / 100) / 10,
      appId,
      chatId,
      outLinkUid,
      answer: '',
      raw: '',
      parsedEventCount: 0,
      records: null,
      trace,
      error: String(error?.stack || error)
    };
  }
}

const results = new Array(cases.length);
let cursor = 0;
const concurrency = 2;

async function worker(workerId) {
  while (true) {
    const index = cursor++;
    if (index >= cases.length) return;
    const result = await runCase(cases[index], index);
    results[index] = result;
    console.log(`[worker ${workerId}] [${index + 1}/${cases.length}] ${result.id} ${result.status} ${result.durationSeconds}s ${result.answer.length} chars`);
    await fs.writeFile(`${OUT}/results.partial.json`, JSON.stringify({ testedAt: new Date().toISOString(), results: results.filter(Boolean) }, null, 2));
    await sleep(800);
  }
}

await Promise.all(Array.from({ length: concurrency }, (_, i) => worker(i + 1)));

const payload = {
  target: `${BASE}/chat/share?shareId=${SHARE_ID}`,
  testedAt: new Date().toISOString(),
  count: results.length,
  ok: results.filter(r => r.status === 'ok').length,
  results
};
await fs.writeFile(`${OUT}/results.json`, JSON.stringify(payload, null, 2));

const md = [
  '# 深圳猫网 AI 助手黑箱测试：原始回答',
  '',
  `- 测试时间：${payload.testedAt}`,
  `- 场景数：${payload.count}`,
  `- 成功提取回答：${payload.ok}`,
  '',
  ...results.flatMap(r => [
    `## ${r.id} · ${r.category} · ${r.status}`,
    '',
    `**问题：** ${r.q}`,
    '',
    '**回答：**',
    '',
    r.answer || `_(未提取到回答：${r.error || `HTTP ${r.httpStatus}`})_`,
    '',
    `响应时间：${r.durationSeconds}s`,
    ''
  ])
].join('\n');
await fs.writeFile(`${OUT}/raw-results.md`, md);

if (payload.ok < Math.ceil(cases.length * 0.8)) process.exitCode = 1;
