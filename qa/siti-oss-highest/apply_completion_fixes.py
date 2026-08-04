#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEGACY = Path(os.environ.get('SITI_LEGACY_AUDIT_SCRIPTS', 'qa/siti-oss-final'))
SERVER = Path(os.environ.get('SITI_SERVER_SOURCE', 'targets/server'))
REPORTCARDS = Path(os.environ.get('SITI_REPORTCARDS_SOURCE', 'targets/reportcards'))

# Apply the previously reviewed candidate patch stack first.
runpy.run_path(str(LEGACY / 'apply_gate_fixes_v3.py'), run_name='__main__')


def read_normalized(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    return raw.decode('utf-8').replace('\r\n', '\n'), newline


def write_preserve(path: Path, text: str, newline: str) -> None:
    normalized = text.replace('\r\n', '\n')
    if newline == '\r\n':
        normalized = normalized.replace('\n', '\r\n')
    path.write_bytes(normalized.encode('utf-8'))


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text, newline = read_normalized(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected one anchor in {path}, found {count}')
    write_preserve(path, text.replace(old, new, 1), newline)


# The raw CommonJS entrypoint is injected as a browser-global script by
# angular.json and executes `exports.*` without a CommonJS wrapper. Use the
# package's browser UMD bundle instead.
angular_json = REPORTCARDS / 'angular.json'
replace_once(
    angular_json,
    'node_modules/leaflet-geosearch/lib/index.js',
    'node_modules/leaflet-geosearch/dist/bundle.min.js',
    'browser-safe leaflet-geosearch bundle',
)

# Permit an S3-compatible endpoint only when explicitly configured. Production
# defaults remain unchanged, while the isolated validation can exercise real
# signature enforcement against MinIO rather than intercepting the PUT.
config_js = SERVER / 'src/config.js'
replace_once(
    config_js,
    "  AWS_S3_SIGNATURE_VERSION: process.env.AWS_SIGNATURE_VERSION || 'v4',\n",
    "  AWS_S3_SIGNATURE_VERSION: process.env.AWS_SIGNATURE_VERSION || 'v4',\n"
    "  AWS_S3_ENDPOINT: process.env.AWS_S3_ENDPOINT || '',\n"
    "  AWS_S3_FORCE_PATH_STYLE: process.env.AWS_S3_FORCE_PATH_STYLE === 'true' || false,\n",
    'optional S3-compatible endpoint configuration',
)

cards_route = SERVER / 'src/api/routes/cards/index.js'
replace_once(
    cards_route,
    '''  let s3 = new AWS.S3({
    accessKeyId: config.AWS_S3_ACCESS_KEY_ID,
    secretAccessKey: config.AWS_S3_SECRET_ACCESS_KEY,
    signatureVersion: config.AWS_S3_SIGNATURE_VERSION,
    region: config.AWS_REGION,
  });''',
    '''  let s3 = new AWS.S3({
    accessKeyId: config.AWS_S3_ACCESS_KEY_ID,
    secretAccessKey: config.AWS_S3_SECRET_ACCESS_KEY,
    signatureVersion: config.AWS_S3_SIGNATURE_VERSION,
    region: config.AWS_REGION,
    endpoint: config.AWS_S3_ENDPOINT || undefined,
    s3ForcePathStyle: config.AWS_S3_FORCE_PATH_STYLE,
  });''',
    'optional S3-compatible endpoint use',
)

print(json.dumps({
    'status': 'completion fixes applied',
    'server': str(SERVER),
    'reportcards': str(REPORTCARDS),
    'changes': [
        'browser-safe leaflet-geosearch UMD bundle',
        'optional S3-compatible endpoint for enforcement testing',
    ],
}, indent=2))
