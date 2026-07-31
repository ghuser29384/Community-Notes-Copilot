#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

import requests

ORIGIN = os.environ.get('SITI_PROD_ORIGIN', 'https://petabencana.id')
OUT = Path(os.environ.get('SITI_PROVENANCE_OUT', 'artifacts/production-provenance'))
OUT.mkdir(parents=True, exist_ok=True)
REPOS = OUT / 'public-repos'
REPOS.mkdir(exist_ok=True)
TOKEN = os.environ.get('GITHUB_TOKEN', '')
SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'SitiOSS-Public-Provenance-Audit/2026-07-31',
    **({'Authorization': f'Bearer {TOKEN}'} if TOKEN else {}),
})

TEXT_SUFFIXES = {
    '.js', '.jsx', '.ts', '.tsx', '.json', '.md', '.html', '.css', '.scss', '.less',
    '.py', '.yml', '.yaml', '.toml', '.txt', '.env', '.sql', '.sh', '.mjs', '.cjs',
}
SKIP_PARTS = {
    '.git', 'node_modules', 'dist', 'build', '.next', 'coverage', 'vendor', 'scripts',
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
}
GENERIC = {
    'use strict', 'application/json', 'application/javascript', 'content-type',
    'undefined', 'function', 'object', 'string', 'boolean', 'number', 'default',
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get(url: str) -> requests.Response:
    response = SESSION.get(url, timeout=45)
    response.raise_for_status()
    return response


def fetch_page(path: str) -> dict:
    url = urljoin(ORIGIN + '/', path.lstrip('/'))
    response = get(url)
    body = response.content
    return {
        'url': url,
        'status': response.status_code,
        'headers': dict(response.headers),
        'bytes': len(body),
        'sha256': sha256(body),
        'text': response.text,
    }


def extract_scripts(html: str, base: str) -> list[str]:
    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)', html, flags=re.I)
    return list(dict.fromkeys(urljoin(base, value) for value in scripts))


def extract_build_candidates(html: str) -> list[str]:
    candidates = set()
    for pattern in [
        r'"buildId"\s*:\s*"([A-Za-z0-9_-]{8,80})"',
        r'buildId\\?"\s*:\s*\\?"([A-Za-z0-9_-]{8,80})',
        r'/_next/static/([A-Za-z0-9_-]{8,80})/(?:_buildManifest|_ssgManifest)',
    ]:
        candidates.update(re.findall(pattern, html))
    return sorted(candidates)


def extract_strings(text: str) -> list[str]:
    values = []
    patterns = [
        r'"([^"\\\n\r]{18,220})"',
        r"'([^'\\\n\r]{18,220})'",
        r'`([^`\\]{18,220})`',
    ]
    for pattern in patterns:
        for value in re.findall(pattern, text):
            value = value.strip()
            if not value or value.lower() in GENERIC:
                continue
            if len(set(value)) < 5:
                continue
            if re.fullmatch(r'[A-Za-z0-9_./:+?=&%#@ -]+', value) is None:
                continue
            if value.count(';') > 3 or value.count('{') > 1 or value.count('}') > 1:
                continue
            values.append(value)
    return values


def list_public_repos() -> list[dict]:
    repos = []
    page = 1
    while True:
        response = SESSION.get(
            'https://api.github.com/orgs/petabencana/repos',
            params={'per_page': 100, 'page': page, 'type': 'public', 'sort': 'full_name'},
            timeout=45,
        )
        response.raise_for_status()
        batch = response.json()
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def clone_repo(repo: dict) -> dict:
    dest = REPOS / repo['name']
    result = run(['git', 'clone', '--filter=blob:none', '--depth', '200', repo['clone_url'], str(dest)])
    if result.returncode != 0:
        return {'repo': repo['full_name'], 'ok': False, 'stderr': result.stderr[-3000:]}
    head = run(['git', 'rev-parse', 'HEAD'], cwd=dest).stdout.strip()
    return {'repo': repo['full_name'], 'ok': True, 'head': head, 'path': str(dest)}


def iter_text_files(root: Path):
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & SKIP_PARTS:
            continue
        if path.name in SKIP_PARTS or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            yield path
        except OSError:
            continue


def load_repo_corpus(root: Path) -> tuple[str, dict[str, str], dict]:
    files = {}
    metadata = {'next_dependencies': [], 'package_files': []}
    combined = []
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        rel = str(path.relative_to(root))
        files[rel] = text
        combined.append(text)
        if path.name == 'package.json':
            metadata['package_files'].append(rel)
            try:
                package = json.loads(text)
                all_deps = {**package.get('dependencies', {}), **package.get('devDependencies', {})}
                if 'next' in all_deps:
                    metadata['next_dependencies'].append({'path': rel, 'version': all_deps['next']})
            except Exception:
                pass
    return '\n'.join(combined), files, metadata


def score_matches(candidates: list[str], corpus: str, files: dict[str, str]) -> dict:
    exact = []
    for candidate in candidates:
        if candidate in corpus:
            hits = [path for path, text in files.items() if candidate in text][:20]
            exact.append({'string': candidate, 'length': len(candidate), 'files': hits})
    exact.sort(key=lambda item: (-item['length'], item['string']))
    return {
        'exact_match_count': len(exact),
        'matched_character_total': sum(item['length'] for item in exact),
        'top_exact_matches': exact[:100],
    }


def commit_search(root: Path, matches: list[dict]) -> list[dict]:
    results = []
    for match in matches[:10]:
        value = match['string']
        if len(value) < 30:
            continue
        proc = run(['git', 'log', '--all', '--format=%H%x09%cI%x09%s', '-S', value, '--'], cwd=root)
        lines = [line for line in proc.stdout.splitlines() if line.strip()][:20]
        if lines:
            results.append({'string': value, 'commits': lines})
    return results


def main() -> None:
    pages = [fetch_page('/'), fetch_page('/map')]
    for index, page in enumerate(pages):
        (OUT / f'page-{index}.html').write_text(page.pop('text'), encoding='utf-8')

    scripts = []
    for index in range(len(pages)):
        html = (OUT / f'page-{index}.html').read_text(encoding='utf-8')
        scripts.extend(extract_scripts(html, pages[index]['url']))
    scripts = list(dict.fromkeys(scripts))

    assets = []
    production_strings = []
    for index, url in enumerate(scripts):
        try:
            response = get(url)
            body = response.content
            suffix = '.js' if 'javascript' in response.headers.get('content-type', '') or url.endswith('.js') else '.bin'
            filename = OUT / f'asset-{index:03d}{suffix}'
            filename.write_bytes(body)
            text = response.text if suffix == '.js' else ''
            strings = extract_strings(text)
            production_strings.extend(strings)
            assets.append({
                'url': url,
                'status': response.status_code,
                'bytes': len(body),
                'sha256': sha256(body),
                'file': filename.name,
                'string_count': len(strings),
                'source_map_comment': re.findall(r'[#@] sourceMappingURL=([^\s]+)', text)[-3:],
            })
        except Exception as exc:
            assets.append({'url': url, 'error': repr(exc)})

    all_html = '\n'.join((OUT / f'page-{i}.html').read_text(encoding='utf-8') for i in range(len(pages)))
    build_candidates = extract_build_candidates(all_html)

    counts = Counter(production_strings)
    candidates = []
    for value, count in counts.items():
        score = len(value) + (35 if 'http' in value else 0) + (20 if '/' in value else 0) - 10 * max(0, count - 1)
        if len(value) >= 26 and count <= 4:
            candidates.append((score, value))
    candidates = [value for _score, value in sorted(candidates, reverse=True)[:1500]]
    (OUT / 'production-candidate-strings.json').write_text(json.dumps(candidates, indent=2), encoding='utf-8')

    repos = list_public_repos()
    clone_results = [clone_repo(repo) for repo in repos if not repo.get('archived')]
    repo_results = []
    for clone in clone_results:
        if not clone.get('ok'):
            repo_results.append(clone)
            continue
        root = Path(clone['path'])
        corpus, files, metadata = load_repo_corpus(root)
        matching = score_matches(candidates, corpus, files)
        commits = commit_search(root, matching['top_exact_matches'])
        repo_results.append({
            'repo': clone['repo'],
            'head': clone['head'],
            **metadata,
            **matching,
            'commit_search': commits,
        })

    repo_results.sort(key=lambda item: (-item.get('matched_character_total', 0), -item.get('exact_match_count', 0), item['repo']))
    attributable = [
        item for item in repo_results
        if item.get('matched_character_total', 0) >= 300 and item.get('exact_match_count', 0) >= 3
    ]

    result = {
        'generated_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        'origin': ORIGIN,
        'pages': pages,
        'scripts': assets,
        'build_id_candidates': build_candidates,
        'public_repo_count': len(repos),
        'cloned_repo_count': sum(1 for item in clone_results if item.get('ok')),
        'candidate_string_count': len(candidates),
        'repo_results': repo_results,
        'attributable_public_source_candidates': attributable,
        'exact_git_sha_publicly_attributable': bool(attributable and any(item.get('commit_search') for item in attributable)),
        'interpretation': (
            'At least one public repository contains multiple uncommon production-bundle strings; commit history requires manual attribution.'
            if attributable else
            'No public petabencana repository met the conservative multi-string attribution threshold. Public evidence does not expose an attributable production Git SHA.'
        ),
    }
    (OUT / 'production-source-attribution.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

    with (OUT / 'public-repository-comparison.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['repository', 'head', 'next_dependencies', 'exact_match_count', 'matched_character_total', 'commit_search_hits'])
        for item in repo_results:
            writer.writerow([
                item['repo'], item.get('head', ''), json.dumps(item.get('next_dependencies', [])),
                item.get('exact_match_count', 0), item.get('matched_character_total', 0), len(item.get('commit_search', [])),
            ])

    print(json.dumps({
        'pages': len(pages),
        'scripts': len(assets),
        'public_repos': len(repos),
        'cloned': sum(1 for item in clone_results if item.get('ok')),
        'build_candidates': build_candidates,
        'attributable_candidates': [item['repo'] for item in attributable],
        'exact_sha_publicly_attributable': result['exact_git_sha_publicly_attributable'],
        'interpretation': result['interpretation'],
    }, indent=2))


if __name__ == '__main__':
    main()
