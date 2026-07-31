#!/usr/bin/env python3
from pathlib import Path
import os

path = Path(os.environ.get('SITI_SERVER_SOURCE', 'targets/server')) / 'src/api/routes/cards/index.js'
text = path.read_text(encoding='utf-8')
old = '''        const errors = [err].concat((err && err.errors) || []);
        const duplicateReport = errors.some((entry) => {
          const candidate = entry && (entry.error || entry);
          return candidate && candidate.code === "23505" &&
            candidate.constraint === "reports_card_id_key";
        });'''
new = '''        const errors = [err].concat((err && err.errors) || []);
        const duplicateText = String(err && (err.message || err));
        const duplicateReport = errors.some((entry) => {
          const candidate = entry && (entry.error || entry);
          return candidate && candidate.code === "23505" &&
            candidate.constraint === "reports_card_id_key";
        }) || (duplicateText.indexOf("duplicate key value") !== -1 &&
          duplicateText.indexOf("reports_card_id_key") !== -1);'''
if text.count(old) != 1:
    raise SystemExit(f'expected one duplicate detection block, found {text.count(old)}')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print(path)
