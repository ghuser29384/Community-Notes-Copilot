import fs from 'node:fs';
const file = process.argv[2];
const result = JSON.parse(fs.readFileSync(file, 'utf8'));
const byId = new Map((result.tests || []).map(x => [x.id, x]));
const expected = {
  'RC-D-001': 'EXECUTED_PASS',
  'RC-M-001': 'EXECUTED_PASS',
  'RC-CLS-001': 'EXECUTED_PASS',
  'RC-SRC-002': 'SOURCE_PASS',
  'RC-SRC-003': 'SOURCE_PASS',
};
const checks = Object.entries(expected).map(([id, status]) => ({
  id,
  expected: status,
  actual: byId.get(id)?.status || 'MISSING',
  title: byId.get(id)?.title || '',
}));
console.log(JSON.stringify(checks, null, 2));
if (checks.some(x => x.actual !== x.expected)) process.exit(1);
