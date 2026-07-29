#!/usr/bin/env python3
"""Generate a source/provenance inventory for a multi-repository Siti OSS audit."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("SITI_TARGET_ROOT", "targets")).resolve()
OUT = Path(os.environ.get("SITI_AUDIT_OUT", "artifacts/discovery")).resolve()
OUT.mkdir(parents=True, exist_ok=True)

TEXT_SUFFIXES = {
    ".js", ".ts", ".tsx", ".jsx", ".json", ".html", ".css", ".scss", ".less",
    ".md", ".yml", ".yaml", ".sql", ".sh", ".py", ".toml", ".env", ".txt",
}
SKIP_PARTS = {".git", "node_modules", "dist", "build", "coverage", ".cache", "vendor"}
PATTERNS: dict[str, re.Pattern[str]] = {
    "api_url": re.compile(r"https?://[^\s'\"<>]+", re.I),
    "possible_secret_name": re.compile(r"\b(secret|token|api[_-]?key|password|private[_-]?key|access[_-]?key)\b", re.I),
    "mapbox_token": re.compile(r"pk\.[A-Za-z0-9._-]{20,}"),
    "captcha": re.compile(r"captcha|recaptcha", re.I),
    "rate_limit": re.compile(r"rate.?limit|throttl", re.I),
    "location": re.compile(r"latitude|longitude|lat\b|lng\b|geolocation|coordinates", re.I),
    "pii": re.compile(r"phone|email|name|user[_-]?id|social|twitter|telegram|whatsapp|facebook", re.I),
    "logging": re.compile(r"console\.(log|warn|error)|logger\.|winston", re.I),
    "image_upload": re.compile(r"image|photo|upload|s3|signed.?url|exif", re.I),
    "authz": re.compile(r"role|permission|authori[sz]|authenticat|jwt|bearer", re.I),
    "xss_sink": re.compile(r"innerHTML|bypassSecurityTrust|dangerouslySetInnerHTML|\.html\(", re.I),
    "dynamic_eval": re.compile(r"\beval\s*\(|new\s+Function\s*\(", re.I),
    "sql_dynamic": re.compile(r"\b(query|execute)\s*\([^\n]*\+|format\s*\([^\n]*SELECT", re.I),
    "todo_fixme": re.compile(r"TODO|FIXME|HACK|XXX", re.I),
}


def run(repo: Path, *args: str) -> str:
    return subprocess.check_output(args, cwd=repo, text=True, stderr=subprocess.DEVNULL).strip()


def is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {
        "Dockerfile", "Makefile", "Procfile", ".env.example", ".env.sample", "LICENSE"
    }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > 2_000_000:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def repo_info(repo: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    files: list[Path] = []
    suffixes: Counter[str] = Counter()
    total_bytes = 0
    for path in repo.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        files.append(path)
        total_bytes += path.stat().st_size
        suffixes[path.suffix.lower() or "[none]"] += 1

    manifest: dict[str, Any] = {}
    package = repo / "package.json"
    if package.exists():
        try:
            manifest = json.loads(package.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            manifest = {"parse_error": str(exc)}

    git = {
        "sha": run(repo, "git", "rev-parse", "HEAD"),
        "branch": run(repo, "git", "branch", "--show-current"),
        "committed_at": run(repo, "git", "show", "-s", "--format=%cI", "HEAD"),
        "commit_subject": run(repo, "git", "show", "-s", "--format=%s", "HEAD"),
        "remote": run(repo, "git", "remote", "get-url", "origin"),
    }

    lockfiles = [p.name for p in repo.iterdir() if p.name in {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "Pipfile.lock", "poetry.lock"}]
    workflows = [str(p.relative_to(repo)) for p in (repo / ".github" / "workflows").glob("*") if p.is_file()] if (repo / ".github" / "workflows").exists() else []
    test_files = [str(p.relative_to(repo)) for p in files if re.search(r"(^|/)(test|tests|spec|e2e)(/|$)|\.(spec|test)\.", str(p.relative_to(repo)), re.I)]

    info = {
        "repo": repo.name,
        **git,
        "file_count": len(files),
        "source_bytes": total_bytes,
        "top_suffixes": suffixes.most_common(15),
        "package_name": manifest.get("name"),
        "package_version": manifest.get("version"),
        "node_engine": (manifest.get("engines") or {}).get("node") if isinstance(manifest.get("engines"), dict) else None,
        "scripts": manifest.get("scripts", {}),
        "dependencies": len(manifest.get("dependencies", {}) or {}),
        "dev_dependencies": len(manifest.get("devDependencies", {}) or {}),
        "lockfiles": lockfiles,
        "workflows": workflows,
        "test_file_count": len(test_files),
        "test_files_sample": test_files[:50],
    }

    hits: list[dict[str, Any]] = []
    for path in files:
        if not is_text(path):
            continue
        text = read_text(path)
        if text is None:
            continue
        rel = str(path.relative_to(repo))
        for line_no, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in PATTERNS.items():
                if pattern.search(line):
                    clean = line.strip()
                    if len(clean) > 500:
                        clean = clean[:500] + "…"
                    hits.append({"repo": repo.name, "kind": kind, "path": rel, "line": line_no, "text": clean})
    return info, hits


def main() -> None:
    repos = sorted([p for p in ROOT.iterdir() if p.is_dir() and (p / ".git").exists()])
    inventory: list[dict[str, Any]] = []
    all_hits: list[dict[str, Any]] = []
    checksums: list[dict[str, str]] = []

    for repo in repos:
        info, hits = repo_info(repo)
        inventory.append(info)
        all_hits.extend(hits)
        for name in ["package.json", "package-lock.json", "README.md", "Dockerfile", "docker-compose.yml"]:
            p = repo / name
            if p.exists() and p.is_file():
                checksums.append({"repo": repo.name, "path": name, "sha256": sha256(p)})

    (OUT / "repo-inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "source-risk-hits.json").write_text(json.dumps(all_hits, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "manifest-checksums.json").write_text(json.dumps(checksums, ensure_ascii=False, indent=2), encoding="utf-8")

    with (OUT / "repo-inventory.csv").open("w", encoding="utf-8", newline="") as f:
        fields = ["repo", "sha", "branch", "committed_at", "commit_subject", "remote", "file_count", "source_bytes", "package_name", "package_version", "node_engine", "dependencies", "dev_dependencies", "lockfiles", "workflows", "test_file_count"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in inventory:
            flat = {k: row.get(k) for k in fields}
            flat["lockfiles"] = ";".join(row.get("lockfiles", []))
            flat["workflows"] = ";".join(row.get("workflows", []))
            writer.writerow(flat)

    with (OUT / "source-risk-hits.csv").open("w", encoding="utf-8", newline="") as f:
        fields = ["repo", "kind", "path", "line", "text"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_hits)

    summary = {
        "repo_count": len(inventory),
        "repos": [r["repo"] for r in inventory],
        "risk_hit_counts": Counter(h["kind"] for h in all_hits),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=dict))


if __name__ == "__main__":
    main()
