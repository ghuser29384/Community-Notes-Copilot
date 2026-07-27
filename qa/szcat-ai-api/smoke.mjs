import fs from 'node:fs/promises';
import crypto from 'node:crypto';

const endpoints = [
  'https://ai.szcat.org/api/v1/chat/completions',
  'https://ai.szcat.org/api/v2/chat/completions'
];
const shareId = 'esavvfKO6VFbAYH5mnP9yhWR';
const question = '我今天在南山区捡到一只后腿完全不能动的流浪猫，现在应该先做什么？猫网能提供什么帮助？';
const attempts = [];

await fs.mkdir('artifacts/szcat-ai-api-smoke', { recursive: true });

for (const endpoint of endpoints) {
  for (const authVariant of ['none', 'shareId-bearer']) {
    const headers = {
      'content-type': 'application/json',
      'accept': 'application/json, text/event-stream'
    };
    if (authVariant === 'shareId-bearer') headers.authorization = `Bearer ${shareId}`;
    const body = {
      shareId,
      chatId: `audit-${crypto.randomUUID()}`,
      stream: false,
      detail: true,
      messages: [{ role: 'user', content: question }]
    };
    const started = Date.now();
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        redirect: 'follow',
        signal: AbortSignal.timeout(90_000)
      });
      const text = await response.text();
      attempts.push({ endpoint, authVariant, status: response.status, ok: response.ok, durationMs: Date.now() - started, headers: Object.fromEntries(response.headers), text });
      console.log(endpoint, authVariant, response.status, text.slice(0, 500));
      if (response.ok && text.length > 20) break;
    } catch (error) {
      attempts.push({ endpoint, authVariant, error: String(error?.stack || error), durationMs: Date.now() - started });
    }
  }
  if (attempts.some(x => x.ok && x.text?.length > 20)) break;
}

await fs.writeFile('artifacts/szcat-ai-api-smoke/result.json', JSON.stringify({ testedAt: new Date().toISOString(), shareId, question, attempts }, null, 2));
if (!attempts.some(x => x.ok && x.text?.length > 20)) process.exitCode = 1;
