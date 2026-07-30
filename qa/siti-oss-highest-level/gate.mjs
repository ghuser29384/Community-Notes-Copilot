import fs from 'node:fs';
const p = process.argv[2];
const r = JSON.parse(fs.readFileSync(p, 'utf8'));
const unresolved = (r.tests || []).filter(x => x.severity === 'P0' && !['EXECUTED_PASS','SOURCE_PASS'].includes(x.status));
console.log(JSON.stringify({ total: r.tests.length, unresolvedP0: unresolved.map(x => ({id:x.id,title:x.title,status:x.status})) }, null, 2));
if (unresolved.length) process.exit(1);
