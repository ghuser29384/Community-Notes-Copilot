import fs from 'node:fs';
import path from 'node:path';

const input = process.argv[2];
const output = process.argv[3];
const targetRoot = process.argv[4];
const raw = JSON.parse(fs.readFileSync(input, 'utf8'));
const result = structuredClone(raw);
const tests = result.tests || [];
const byId = new Map(tests.map(x => [x.id, x]));

function upsert(test) {
  const existing = byId.get(test.id);
  if (existing) Object.assign(existing, test);
  else { tests.push(test); byId.set(test.id, test); }
}
function scenarioHasRuntimeError(scenario) {
  return (result.pageErrors || []).some(x => x.scenario === scenario && /exports is not defined/.test(x.error || ''));
}

const runtimeErrors = (result.pageErrors || []).filter(x => /exports is not defined/.test(x.error || ''));
upsert({
  id: 'RC-RUNTIME-001',
  title: 'Built Report Cards application runs without an uncaught CommonJS global error',
  status: runtimeErrors.length ? 'EXECUTED_FAIL' : 'EXECUTED_PASS',
  severity: runtimeErrors.length ? 'P0' : 'P2',
  evidence: { count: runtimeErrors.length, examples: runtimeErrors.slice(0, 5) },
  recommendation: 'Do not concatenate leaflet-geosearch/lib/index.js as a global script. The application already imports the package through Angular; remove the redundant CommonJS global entry and rerun every flow.',
});

if (targetRoot) {
  const angularPath = path.join(targetRoot, 'angular.json');
  const angularText = fs.readFileSync(angularPath, 'utf8');
  const badGlobal = angularText.includes('node_modules/leaflet-geosearch/lib/index.js');
  upsert({
    id: 'RC-SRC-006',
    title: 'Angular global scripts exclude the CommonJS leaflet-geosearch entry point',
    status: badGlobal ? 'SOURCE_FAIL' : 'SOURCE_PASS',
    severity: badGlobal ? 'P0' : 'P2',
    evidence: { badGlobal, angularPath: 'angular.json' },
    recommendation: 'Remove node_modules/leaflet-geosearch/lib/index.js from angular.json global scripts; retain the typed module imports in the application code.',
  });
}

const runtimeBlocked = [
  ['RC-D-001', 'flood-training-desktop'],
  ['RC-M-001', 'flood-training-mobile'],
  ['RC-CLS-001', 'real-report-training-word-classification'],
  ['RC-IMG-001', 'photo-metadata-upload'],
  ['RC-ROUTE-001', 'route-inventory'],
];
for (const [id, scenario] of runtimeBlocked) {
  const t = byId.get(id);
  if (t && scenarioHasRuntimeError(scenario) && !['EXECUTED_PASS','SOURCE_PASS'].includes(t.status)) {
    t.status = 'BLOCKED_BY_RUNTIME';
    t.evidence = { ...(t.evidence || {}), prerequisiteFailure: 'RC-RUNTIME-001' };
  }
}

const invalidAuth = byId.get('RC-AUTH-001');
if (invalidAuth) {
  invalidAuth.status = 'INVALID_TEST_CONFIGURATION';
  invalidAuth.severity = 'P2';
  invalidAuth.evidence = { ...(invalidAuth.evidence || {}), reason: 'The original audit mock returned a successful card response for every token, including unknown-token; this result cannot establish fail-open behavior.' };
  invalidAuth.recommendation = 'Retest with the card lookup returning 404 or 403 for an unknown token, then verify that the UI fails closed.';
}

const mapboxEvents = (result.networkMutations || []).filter(x => /events\.mapbox\.com/.test(x.url || ''));
upsert({
  id: 'RC-PRIV-001',
  title: 'Third-party Mapbox telemetry is documented and tested as part of the report flow',
  status: mapboxEvents.length ? 'EXECUTED_OBSERVATION' : 'NOT_OBSERVED',
  severity: 'P1',
  evidence: { requestCount: mapboxEvents.length, sampleUrls: [...new Set(mapboxEvents.map(x => x.url))].slice(0, 3), sampleBodies: mapboxEvents.slice(0, 2).map(x => x.postData) },
  recommendation: 'Document required Mapbox billing/telemetry requests, review identifiers and retention, and ensure privacy disclosures distinguish these third-party requests from disaster report submission.',
});

const statusCounts = tests.reduce((a, x) => (a[x.status] = (a[x.status] || 0) + 1, a), {});
const severityCounts = tests.reduce((a, x) => (a[x.severity] = (a[x.severity] || 0) + 1, a), {});
const nonFailStatuses = new Set(['EXECUTED_PASS','SOURCE_PASS','NOT_OBSERVED','EXECUTED_OBSERVATION','INVALID_TEST_CONFIGURATION']);
result.summary = {
  count: tests.length,
  statusCounts,
  severityCounts,
  unresolvedP0: tests.filter(x => x.severity === 'P0' && !nonFailStatuses.has(x.status)).map(x => ({ id: x.id, title: x.title, status: x.status })),
  blocked: tests.filter(x => String(x.status).startsWith('BLOCKED')).map(x => ({ id: x.id, title: x.title, status: x.status })),
  invalidTests: tests.filter(x => String(x.status).startsWith('INVALID')).map(x => ({ id: x.id, title: x.title })),
  pageErrorCount: (result.pageErrors || []).length,
  runtimeErrorCount: runtimeErrors.length,
};
fs.writeFileSync(output, JSON.stringify(result, null, 2));
console.log(JSON.stringify(result.summary, null, 2));
