#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

OUT = Path(__import__('os').environ.get('SITI_PROVENANCE_OUT', 'artifacts/production-provenance'))
source_path = OUT / 'production-source-attribution.json'
data = json.loads(source_path.read_text(encoding='utf-8'))

html = '\n'.join(
    path.read_text(encoding='utf-8', errors='ignore')
    for path in sorted(OUT.glob('page-*.html'))
)
build_ids = set(data.get('build_id_candidates') or [])
for pattern in [
    r'"b"\s*:\s*"([A-Za-z0-9_-]{8,80})"',
    r'\\"b\\"\s*:\s*\\"([A-Za-z0-9_-]{8,80})\\"',
    r'"buildId"\s*:\s*"([A-Za-z0-9_-]{8,80})"',
    r'/_next/static/([A-Za-z0-9_-]{8,80})/(?:_buildManifest|_ssgManifest)',
]:
    build_ids.update(re.findall(pattern, html))

lineage = data.pop('attributable_public_source_candidates', [])
for item in lineage:
    item['classification'] = 'lineage evidence only'
    item['attribution_limit'] = (
        'Matching strings can persist across many commits or be copied into a different framework. '
        'They do not identify the deployed commit.'
    )

data['build_id_candidates'] = sorted(build_ids)
data['public_source_lineage_candidates'] = lineage
data['exact_git_sha_publicly_attributable'] = False
data['exact_git_sha_reason'] = (
    'The current production deployment exposes a Next.js build ID and asset hashes, but no Git commit metadata, '
    'source map with commit provenance, reproducible build manifest, or exact asset-to-tree hash mapping. '
    'Multiple uncommon strings overlap with the public disastermap lineage, but git -S shows those strings across '
    'multiple historical commits; therefore they cannot identify one deployed SHA.'
)
data['strongest_public_conclusion'] = (
    'Current production shares textual and asset lineage with public PetaBencana repositories, especially '
    'petabencana/disastermap, while the exact production Git SHA remains publicly unverifiable.'
)
data['interpretation'] = data['strongest_public_conclusion']

corrected_path = OUT / 'production-source-attribution-corrected.json'
corrected_path.write_text(json.dumps(data, indent=2), encoding='utf-8')

summary = {
    'origin': data.get('origin'),
    'next_build_ids': data['build_id_candidates'],
    'public_repo_count': data.get('public_repo_count'),
    'cloned_repo_count': data.get('cloned_repo_count'),
    'lineage_candidates': [
        {
            'repo': item.get('repo'),
            'head': item.get('head'),
            'exact_match_count': item.get('exact_match_count'),
            'matched_character_total': item.get('matched_character_total'),
        }
        for item in lineage
    ],
    'exact_git_sha_publicly_attributable': False,
    'conclusion': data['strongest_public_conclusion'],
}
(OUT / 'production-source-attribution-summary.json').write_text(
    json.dumps(summary, indent=2), encoding='utf-8'
)
print(json.dumps(summary, indent=2))
