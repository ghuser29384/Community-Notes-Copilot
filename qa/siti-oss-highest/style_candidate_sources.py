#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

SERVER = Path(os.environ.get('SITI_SERVER_SOURCE', 'targets/server'))
REPORTCARDS = Path(os.environ.get('SITI_REPORTCARDS_SOURCE', 'targets/reportcards'))
HARNESS_VALUE = os.environ.get('SITI_BROWSER_HARNESS', '')


def edit(path: Path, replacements: list[tuple[str, str]]) -> int:
    text = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    changed = 0
    for old, new in replacements:
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            changed += count
    path.write_text(text, encoding='utf-8')
    return changed


route = SERVER / 'src/api/routes/cards/index.js'
route_changes = edit(route, [
    ('import presignPutObject from "../../../lib/presignPutObject";',
     "import presignPutObject from '../../../lib/presignPutObject';"),
    ('req.headers["content-type"]', "req.headers['content-type']"),
    ('.valid("jpeg", "png")', ".valid('jpeg', 'png')"),
    ('err.code === "REPORT_ALREADY_RECEIVED"',
     "err.code === 'REPORT_ALREADY_RECEIVED'"),
    ('candidate.code === "23505"', "candidate.code === '23505'"),
    ('candidate.constraint === "reports_card_id_key"',
     "candidate.constraint === 'reports_card_id_key'"),
    ('logger.debug("s3 signed request generated")',
     "logger.debug('s3 signed request generated')"),
    ('logger.error("could not get signed url for S3")',
     "logger.error('could not get signed url for S3')"),
    ('error: "Could not generate image upload URL"',
     "error: 'Could not generate image upload URL'"),
])

model = SERVER / 'src/api/routes/cards/model.js'
model_changes = edit(model, [
    ('new Error("Card not found")', "new Error('Card not found')"),
    ('missing.code = "CARD_NOT_FOUND"', "missing.code = 'CARD_NOT_FOUND'"),
    ('new Error("Report already received")',
     "new Error('Report already received')"),
    ('conflict.code = "REPORT_ALREADY_RECEIVED"',
     "conflict.code = 'REPORT_ALREADY_RECEIVED'"),
    ('            "Confirmed",', "            'Confirmed',"),
    ('[card.card_id, "REPORT SUBMITTED"]',
     "[card.card_id, 'REPORT SUBMITTED']"),
])

presigner = SERVER / 'src/lib/presignPutObject.js'
presigner_text = presigner.read_text(encoding='utf-8')
# This file is generated entirely by the completion script and contains no
# apostrophes inside JavaScript string literals, so normalizing delimiters is
# deterministic and keeps the new module within the repository's quote rule.
presigner_text = presigner_text.replace('"', "'")
presigner.write_text(presigner_text, encoding='utf-8')

photo_module = REPORTCARDS / 'src/app/routes/cards/photo/photo.module.ts'
photo_changes = edit(photo_module, [
    ("import { CommonModule } from '@angular/common';\n",
     "import { CommonModule } from '@angular/common';\n"
     "import { TranslateModule } from '@ngx-translate/core';\n"),
    ('    CommonModule,\n    PhotoRoutingModule',
     '    CommonModule,\n    TranslateModule,\n    PhotoRoutingModule'),
])

karma = REPORTCARDS / 'karma.conf.js'
karma_changes = edit(karma, [
    (
        "    browsers: ['Chrome'],\n    singleRun: false",
        "    browsers: ['Chrome'],\n"
        "    customLaunchers: {\n"
        "      ChromeHeadlessNoSandbox: {\n"
        "        base: 'ChromeHeadless',\n"
        "        flags: ['--no-sandbox', '--disable-dev-shm-usage']\n"
        "      }\n"
        "    },\n"
        "    singleRun: false"
    ),
])

harness_changes = 0
if HARNESS_VALUE:
    harness = Path(HARNESS_VALUE)
    if harness.exists():
        harness_changes = edit(harness, [
            (
                "    viewport: scenario.viewport || { width: 1365, height: 900 },\n"
                "    geolocation: { latitude: -6.175392, longitude: 106.827153 },",
                "    viewport: scenario.viewport || { width: 1365, height: 900 },\n"
                "    isMobile: Boolean(scenario.viewport && scenario.viewport.width <= 480),\n"
                "    hasTouch: Boolean(scenario.viewport && scenario.viewport.width <= 480),\n"
                "    deviceScaleFactor: scenario.viewport && scenario.viewport.width <= 480 ? 2 : 1,\n"
                "    geolocation: { latitude: -6.175392, longitude: 106.827153 },"
            ),
            (
                "      id: result.scenario.id,\n      errors: result.errors.length,",
                "      id: result.scenario.id,\n"
                "      viewport: result.scenario.viewport || { width: 1365, height: 900 },\n"
                "      errors: result.errors.length,"
            ),
        ])

print({
    'status': 'candidate source style, module dependencies, Karma launcher, and mobile evidence normalized',
    'route_replacements': route_changes,
    'model_replacements': model_changes,
    'photo_module_replacements': photo_changes,
    'karma_replacements': karma_changes,
    'browser_harness_replacements': harness_changes,
    'presigner': str(presigner),
})
