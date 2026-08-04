#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ.get('SITI_BROWSER_HARNESS', 'runner/audit.mjs'))
text = path.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected one anchor, found {count}')
    text = text.replace(old, new, 1)


replace_once(
    "const apiURL = (process.env.SITI_SERVER_URL || 'http://127.0.0.1:8001').replace(/\\/$/, '');\n",
    "const apiURL = (process.env.SITI_SERVER_URL || 'http://127.0.0.1:8001').replace(/\\/$/, '');\n"
    "const objectStorageOrigin = (process.env.SITI_OBJECT_STORAGE_ORIGIN || '').replace(/\\/$/, '');\n",
    'object-storage origin',
)
replace_once(
    "    viewport: { width: 1365, height: 900 },",
    "    viewport: scenario.viewport || { width: 1365, height: 900 },",
    'scenario viewport',
)
replace_once(
    "  page.on('pageerror', error => pageErrors.push(String(error)));",
    "  page.on('pageerror', error => pageErrors.push(error?.stack || String(error)));",
    'page error stack capture',
)
replace_once(
    "    if (/amazonaws\\.com$/.test(url.hostname) && method === 'PUT') {",
    "    if (method === 'PUT' && (\n"
    "        (objectStorageOrigin && url.origin === objectStorageOrigin) ||\n"
    "        /amazonaws\\.com$/.test(url.hostname))) {",
    'object-storage PUT detection',
)
replace_once(
    "      return route.fulfill({ status: 200, headers: { etag: 'audit-etag' }, body: '' });",
    "      if (objectStorageOrigin && url.origin === objectStorageOrigin) {\n"
    "        return route.continue();\n"
    "      }\n"
    "      return route.fulfill({ status: 200, headers: { etag: 'audit-etag' }, body: '' });",
    'real object-storage continuation',
)
replace_once(
    "    { id: 'full-success-no-image' },\n",
    "    { id: 'full-success-no-image' },\n"
    "    { id: 'mobile-success', viewport: { width: 390, height: 844 } },\n",
    'mobile scenario',
)
replace_once(
    "    base_success: Boolean(byId['full-success-no-image']?.reportPersisted && byId['full-success-no-image']?.errors.length === 0),\n",
    "    base_success: Boolean(byId['full-success-no-image']?.reportPersisted && byId['full-success-no-image']?.errors.length === 0),\n"
    "    mobile_success: Boolean(byId['mobile-success']?.reportPersisted && byId['mobile-success']?.errors.length === 0),\n",
    'mobile assertion',
)
replace_once(
    "    no_thank_title_error: results.every(result => !result.consoleMessages.some(message => /reading 'title'/.test(message.text))),\n",
    "    no_thank_title_error: results.every(result => !result.consoleMessages.some(message => /reading 'title'/.test(message.text))),\n"
    "    no_page_errors: results.every(result => result.pageErrors.length === 0),\n",
    'strict page error assertion',
)

path.write_text(text, encoding='utf-8')
print({'status': 'final browser harness patched', 'path': str(path)})
