#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path(os.environ.get('SITI_VALIDATION_OUT', 'artifacts/production-readonly'))
OUT.mkdir(parents=True, exist_ok=True)
UA = 'SitiOSS-Bounded-ReadOnly-Validation/2026-07-30 contact:caijun054@gmail.com'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': UA, 'Accept': 'application/json,text/html,*/*'})
API_URL = 'https://api.petabencana.id/reports?timeperiod=3600'
SITES = ['https://petabencana.id/', 'https://petabencana.id/map', 'https://mapakalamidad.ph/', 'https://mapakalamidad.ph/map']


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (position - low)


def one_get(url, timeout=30):
    started = time.perf_counter()
    try:
        response = SESSION.get(url, timeout=timeout)
        return {
            'status': response.status_code,
            'elapsed_ms': round((time.perf_counter() - started) * 1000, 2),
            'retry_after': response.headers.get('Retry-After'),
            'rate_limit_limit': response.headers.get('X-RateLimit-Limit') or response.headers.get('RateLimit-Limit'),
            'rate_limit_remaining': response.headers.get('X-RateLimit-Remaining') or response.headers.get('RateLimit-Remaining'),
            'server': response.headers.get('Server'),
            'via': response.headers.get('Via'),
            'content_length': len(response.content),
            'body_prefix': response.text[:300],
        }
    except Exception as exc:
        return {'status': None, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 2), 'error': repr(exc)}


def bounded_rate_probe():
    phases = []
    phases.append({'phase': '10_sequential', 'concurrency': 1, 'results': [one_get(API_URL) for _ in range(10)]})
    for wave in range(5):
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _index: one_get(API_URL), range(5)))
        phases.append({'phase': f'5_concurrent_wave_{wave + 1}', 'concurrency': 5, 'results': results})
        time.sleep(0.4)
    for wave in range(2):
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _index: one_get(API_URL), range(10)))
        phases.append({'phase': f'10_concurrent_wave_{wave + 1}', 'concurrency': 10, 'results': results})
        time.sleep(0.8)
    all_results = [result for phase in phases for result in phase['results']]
    return {
        'scope': 'bounded public GET-only probe; 55 requests; not a production load test',
        'request_count': len(all_results),
        'status_counts': dict(Counter(str(result.get('status')) for result in all_results)),
        'latency_ms': {
            'p50': percentile([result['elapsed_ms'] for result in all_results], 0.5),
            'p95': percentile([result['elapsed_ms'] for result in all_results], 0.95),
            'max': max(result['elapsed_ms'] for result in all_results),
        },
        'retry_after_values': sorted({result.get('retry_after') for result in all_results if result.get('retry_after')}),
        'rate_limit_headers_observed': [
            {key: result.get(key) for key in ['rate_limit_limit', 'rate_limit_remaining']}
            for result in all_results
            if result.get('rate_limit_limit') or result.get('rate_limit_remaining')
        ],
        'phases': phases,
    }


def extract_build_metadata():
    pages = []
    assets = []
    candidates = set()
    commit_pattern = re.compile(r'(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])', re.I)
    named_pattern = re.compile(r'(?:VERCEL_GIT_COMMIT_SHA|GIT_COMMIT|COMMIT_SHA|release|buildId|build_id)["\'\s:=]+([A-Za-z0-9._-]{6,80})', re.I)
    for url in SITES:
        record = {'url': url}
        try:
            response = SESSION.get(url, timeout=40)
            record.update({
                'status': response.status_code,
                'headers': dict(response.headers),
                'sha256': hashlib.sha256(response.content).hexdigest(),
                'bytes': len(response.content),
            })
            html = response.text
            filename = f"page-{urlparse(url).netloc}-{hashlib.sha1(url.encode()).hexdigest()[:8]}.html"
            (OUT / filename).write_text(html, encoding='utf-8')
            soup = BeautifulSoup(html, 'html.parser')
            scripts = [urljoin(url, tag.get('src')) for tag in soup.find_all('script') if tag.get('src')]
            next_data = soup.find('script', id='__NEXT_DATA__')
            if next_data and next_data.string:
                try:
                    record['next_data'] = json.loads(next_data.string)
                except Exception:
                    record['next_data_raw'] = next_data.string[:5000]
            record['script_count'] = len(scripts)
            record['scripts'] = scripts[:100]
            for asset_url in scripts[:30]:
                try:
                    asset_response = SESSION.get(asset_url, timeout=40)
                    text = asset_response.text
                    commit_matches = commit_pattern.findall(text)
                    named_matches = named_pattern.findall(text)
                    candidates.update(commit_matches)
                    candidates.update(named_matches)
                    source_maps = [urljoin(asset_url, value) for value in re.findall(r'//# sourceMappingURL=([^\s]+)', text[-1000:])]
                    assets.append({
                        'url': asset_url,
                        'status': asset_response.status_code,
                        'bytes': len(asset_response.content),
                        'sha256': hashlib.sha256(asset_response.content).hexdigest(),
                        'commit_like': commit_matches[:20],
                        'named_metadata': named_matches[:20],
                        'source_maps': source_maps,
                    })
                    for map_url in source_maps[:1]:
                        try:
                            map_response = SESSION.get(map_url, timeout=30)
                            map_text = map_response.text
                            map_commits = commit_pattern.findall(map_text)
                            map_named = named_pattern.findall(map_text)
                            candidates.update(map_commits)
                            candidates.update(map_named)
                            assets.append({
                                'url': map_url,
                                'status': map_response.status_code,
                                'bytes': len(map_response.content),
                                'sha256': hashlib.sha256(map_response.content).hexdigest(),
                                'commit_like': map_commits[:20],
                                'named_metadata': map_named[:20],
                                'is_source_map': True,
                            })
                        except Exception as exc:
                            assets.append({'url': map_url, 'error': repr(exc), 'is_source_map': True})
                except Exception as exc:
                    assets.append({'url': asset_url, 'error': repr(exc)})
        except Exception as exc:
            record['error'] = repr(exc)
        pages.append(record)
    exact_candidates = [value for value in candidates if re.fullmatch(r'[0-9a-fA-F]{40}', value)]
    return {
        'pages': pages,
        'assets': assets,
        'public_commit_or_build_candidates': sorted(candidates),
        'forty_hex_candidates': sorted(exact_candidates),
        'exact_production_sha_exposed': bool(exact_candidates),
        'scope_note': 'A 40-hex candidate is not accepted as a repository mapping unless the deployed repository and commit are independently attributable.',
    }


def main():
    result = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'rate_limit_probe': bounded_rate_probe(),
        'production_fingerprint': extract_build_metadata(),
    }
    (OUT / 'production-readonly-validation.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    print(json.dumps({
        'rate_status_counts': result['rate_limit_probe']['status_counts'],
        'retry_after': result['rate_limit_probe']['retry_after_values'],
        'candidate_count': len(result['production_fingerprint']['public_commit_or_build_candidates']),
        'exact_sha_exposed': result['production_fingerprint']['exact_production_sha_exposed'],
    }, indent=2))


if __name__ == '__main__':
    main()
