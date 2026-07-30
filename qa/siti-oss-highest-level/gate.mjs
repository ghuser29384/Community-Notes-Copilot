import fs from 'node:fs';
const p = process.argv[2];
const r = JSON.parse(fs.readFileSync(p, 'utf8'));
const unresolved = r.summary?.unresolvedP0 || [];
console.log(JSON.stringify({ total: r.tests?.length || 0, unresolvedP0: unresolved }, null, 2));
if (unresolved.length) process.exit(1);
