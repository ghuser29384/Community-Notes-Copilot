import fs from 'node:fs';
import path from 'node:path';

const apiURL = (process.env.SITI_SERVER_URL || 'http://127.0.0.1:8001').replace(/\/$/, '');
const outDir = path.resolve(process.env.SITI_S3_CONTRACT_OUT || 'artifacts/s3-contract');
fs.mkdirSync(outDir, { recursive: true });

async function api(method, route, body, headers = {}) {
  const response = await fetch(apiURL + route, {
    method,
    headers: { 'content-type': 'application/json', ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data;
  try { data = await response.json(); } catch { data = await response.text(); }
  return { status: response.status, data };
}

async function signedURL(label, type) {
  const card = await api('POST', '/cards', {
    username: `s3-contract-${label}`,
    network: 'twitter',
    language: 'en',
    network_data: {},
  });
  if (card.status !== 200) throw new Error(`Card creation failed: ${JSON.stringify(card)}`);
  const response = await fetch(`${apiURL}/cards/${card.data.cardId}/images`, {
    headers: { 'content-type': type },
  });
  const data = await response.json();
  if (response.status !== 200) throw new Error(`Signing failed: ${JSON.stringify({ status: response.status, data })}`);
  return { cardId: card.data.cardId, url: data.signedRequest };
}

const body = Buffer.from('SITI-OSS-CONTENT-TYPE-CONTRACT');
const matching = await signedURL('matching', 'image/png');
const matchingResponse = await fetch(matching.url, {
  method: 'PUT',
  headers: { 'content-type': 'image/png' },
  body,
});

const mismatched = await signedURL('mismatched', 'image/png');
const mismatchedResponse = await fetch(mismatched.url, {
  method: 'PUT',
  headers: { 'content-type': 'image/jpeg' },
  body,
});

const omitted = await signedURL('omitted', 'image/png');
const omittedResponse = await fetch(omitted.url, {
  method: 'PUT',
  body,
});

const result = {
  generatedAt: new Date().toISOString(),
  matching: {
    status: matchingResponse.status,
    url: matching.url,
    responseText: await matchingResponse.text(),
  },
  mismatched: {
    status: mismatchedResponse.status,
    url: mismatched.url,
    responseText: await mismatchedResponse.text(),
  },
  omitted: {
    status: omittedResponse.status,
    url: omitted.url,
    responseText: await omittedResponse.text(),
  },
};
result.pass = result.matching.status >= 200 && result.matching.status < 300 &&
  result.mismatched.status >= 400 && result.omitted.status >= 400;

fs.writeFileSync(path.join(outDir, 's3-content-type-contract.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
if (!result.pass) process.exitCode = 2;
