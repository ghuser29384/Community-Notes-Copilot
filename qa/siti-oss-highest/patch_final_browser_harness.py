#!/usr/bin/env python3
from __future__ import annotations

import os
import runpy
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
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
runpy.run_path(str(ROOT / 'style_candidate_sources.py'), run_name='__main__')

server = Path(os.environ.get('SITI_SERVER_SOURCE', 'targets/server'))
reportcards = Path(os.environ.get('SITI_REPORTCARDS_SOURCE', 'targets/reportcards'))

# Apply the legacy project's own fixable TSLint rules only to files changed by
# this candidate. This removes candidate-added semicolon, brace, whitespace and
# inferrable-type debt without rewriting unrelated historical source files.
tslint = reportcards / 'node_modules/.bin/tslint'
changed_typescript = [
    'src/app/components/image-uploader/image-uploader.component.ts',
    'src/app/components/location-picker/location-picker.component.ts',
    'src/app/components/submit-button/submit-button.component.ts',
    'src/app/services/cards/deck.service.ts',
    'src/app/routes/cards/photo/photo.module.ts',
]
fix = subprocess.run(
    [str(tslint), '--config', 'tslint.json', '--fix', *changed_typescript],
    cwd=reportcards,
    check=False,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
print({
    'tslint_fix_exit': fix.returncode,
    'tslint_fix_output': fix.stdout[-4000:],
})

# npm 6 rewrites lockfileVersion 2 lockfiles when it installs this legacy
# project. The pinned Jasmine package is a validation-tool dependency, not a
# proposed product dependency. Restore package manifests before producing the
# submit-ready product diffs; the already-installed node_modules tree remains.
subprocess.run(
    ['git', 'checkout', '--', 'package-lock.json'],
    cwd=server,
    check=True,
)
subprocess.run(
    ['git', 'checkout', '--', 'package.json', 'package-lock.json'],
    cwd=reportcards,
    check=True,
)

# The legacy Angular/Karma bundle requires more than Node's default heap on the
# current runner. Keep this as an untracked validation-only npm setting so it
# affects lifecycle child processes without entering either candidate patch.
(reportcards / '.npmrc').write_text(
    'node-options=--max_old_space_size=8192\n',
    encoding='utf-8',
)

print({
    'status': 'final browser harness, candidate-local lint fixes, clean diffs, and validation heap prepared',
    'path': str(path),
})
