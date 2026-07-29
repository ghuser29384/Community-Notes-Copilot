#!/usr/bin/env python3
"""Read-only PetaBencana public API audit.

This script deliberately issues GET/HEAD/OPTIONS requests only. It never creates,
updates, deletes, or authenticates to production resources.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

OUT = Path(os.environ.get("SITI_AUDIT_OUT", "artifacts/api")).resolve()
OUT.mkdir(parents=True, exist_ok=True)
BASES = [
    os.environ.get("SITI_API_BASE", "https://api.petabencana.id").rstrip("/"),
    os.environ.get("SITI_DATA_BASE", "https://data.petabencana.id").rstrip("/"),
]
UA = "SitiOSS-Reliability-Audit/2026-07-29 (+read-only; contact via audit owner)"
MAX_BODY = 2_000_000
DELAY_SECONDS = 0.30

NOW = dt.datetime.now(dt.timezone.utc)
START_24H = (NOW - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S%z")
END_NOW = NOW.strftime("%Y-%m-%dT%H:%M:%S%z")

CASES: list[dict[str, Any]] = []

def case(case_id: str, path: str, *, method: str = "GET", expected: str = "documented/read-only behavior", base: str = "api") -> None:
    CASES.append({"id": case_id, "base": base, "method": method, "path": path, "expected": expected})

# Baseline and output-format behavior.
case("API-001", "/reports", expected="200 and current crowdsourced reports")
case("API-002", "/reports?format=json", expected="JSON output")
case("API-003", "/reports?format=xml", expected="documented XML output or explicit validation error")
case("API-004", "/reports?geoformat=topojson", expected="TopoJSON output")
case("API-005", "/reports?geoformat=geojson", expected="GeoJSON output")
case("API-006", "/reports?geoformat=cap", expected="CAP output if still supported, otherwise explicit validation error")
case("API-007", "/reports?timeperiod=3600", expected="reports limited to one hour")
case("API-008", "/reports?timeperiod=86400", expected="reports limited to one day")
case("API-009", "/reports?timeperiod=604800", expected="documented upper-bound behavior")
case("API-010", "/reports?timeperiod=1", expected="documented lower-bound behavior")

# Disaster filters.
for index, disaster in enumerate(["flood", "earthquake", "fire", "haze", "wind", "volcano"], start=11):
    case(f"API-{index:03d}", f"/reports?disaster={disaster}&geoformat=geojson&timeperiod=86400", expected=f"only {disaster} reports")

# Invalid and adversarial query values (still safe GETs).
invalid_cases = [
    ("API-017", "/reports?timeperiod=0", "reject or clamp zero"),
    ("API-018", "/reports?timeperiod=-1", "reject negative"),
    ("API-019", "/reports?timeperiod=604801", "reject or document value above maximum"),
    ("API-020", "/reports?timeperiod=abc", "reject nonnumeric"),
    ("API-021", "/reports?timeperiod=1e3", "reject or consistently parse exponent"),
    ("API-022", "/reports?timeperiod=3600&timeperiod=7200", "deterministic duplicate-parameter handling"),
    ("API-023", "/reports?disaster=unknown", "reject invalid disaster or return empty result without broadening"),
    ("API-024", "/reports?disaster=flood%00earthquake", "reject NUL-like input"),
    ("API-025", "/reports?format=yaml", "reject invalid format"),
    ("API-026", "/reports?geoformat=wkt", "reject invalid geoformat"),
    ("API-027", "/reports?admin=../../etc/passwd", "treat as inert invalid admin filter"),
    ("API-028", "/reports?admin=%27%20OR%201%3D1--", "treat SQL-like input as inert invalid filter"),
    ("API-029", "/reports?unknown_parameter=1", "stable handling of unknown parameter"),
    ("API-030", "/reports?admin=" + "A" * 2048, "bounded handling of very long query value"),
]
for cid, path, expected in invalid_cases:
    case(cid, path, expected=expected)

# Other documented read-only endpoints.
case("API-031", "/admin", expected="supported administrative boundaries")
case("API-032", "/floodgauges", expected="flood gauge data")
case("API-033", "/floods", expected="current flood polygons/status")
case("API-034", "/infrastructure", expected="public infrastructure data")
case("API-035", "/stats/reportsSummary", expected="summary statistics")
case("API-036", f"/reports/timeseries?start={urllib.parse.quote(START_24H)}&end={urllib.parse.quote(END_NOW)}", expected="time series for valid ISO interval")
case("API-037", "/reports/timeseries?start=bad&end=bad", expected="explicit date validation")
case("API-038", f"/reports/archive?start={urllib.parse.quote(START_24H)}&end={urllib.parse.quote(END_NOW)}", expected="authenticated archive behavior without leaking data")
case("API-039", "/cards/test123", expected="authentication/authorization boundary")
case("API-040", "/cards/short", expected="card ID length/input validation")

# Protocol/headers. HEAD and OPTIONS are non-mutating.
case("API-041", "/reports", method="HEAD", expected="consistent headers without body")
case("API-042", "/reports", method="OPTIONS", expected="explicit allowed methods and CORS behavior")
case("API-043", "/does-not-exist", expected="structured 404 without stack trace")
case("API-044", "/reports/", expected="trailing-slash behavior")
case("API-045", "/REPORTS", expected="case sensitivity is explicit")

# Legacy data host documented in examples.
case("API-046", "/reports?timeperiod=3600", base="data", expected="legacy/current data host behavior")
case("API-047", "/stats/reportsSummary", base="data", expected="legacy/current summary endpoint")
case("API-048", "/floodgauges", base="data", expected="legacy/current flood gauge endpoint")

# Encoding and cache consistency.
case("API-049", "/reports?disaster=flood%20", expected="whitespace-normalization behavior")
case("API-050", "/reports?disaster=FLOOD", expected="case-normalization behavior")
case("API-051", "/reports?timeperiod=%2B3600", expected="signed numeric normalization")
case("API-052", "/reports?geoformat=geojson&format=json&timeperiod=3600", expected="combined documented filters")
case("API-053", "/reports?geoformat=geojson&disaster=flood&admin=jbd&timeperiod=3600", expected="combined geographic/disaster filters")
case("API-054", "/reports?geoformat=geojson&disaster=flood&admin=invalid&timeperiod=3600", expected="invalid admin must not broaden data")

SECURITY_HEADERS = [
    "content-security-policy", "strict-transport-security", "x-content-type-options",
    "referrer-policy", "permissions-policy", "cross-origin-resource-policy",
    "cross-origin-opener-policy", "cache-control", "vary", "access-control-allow-origin",
]
PII_KEY = re.compile(r"(^|_)(phone|mobile|email|name|username|user_id|social|twitter|telegram|whatsapp|facebook|address)(_|$)", re.I)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+?62|0)[\s.-]?(?:\d[\s.-]?){8,13}(?!\d)")


def request(url: str, method: str) -> dict[str, Any]:
    req = urllib.request.Request(url, method=method, headers={
        "User-Agent": UA,
        "Accept": "application/json, application/xml;q=0.8, */*;q=0.5",
        "Accept-Encoding": "gzip",
        "Origin": "https://audit.invalid",
    })
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as response:
            raw = response.read(MAX_BODY + 1) if method != "HEAD" else b""
            if response.headers.get("Content-Encoding", "").lower() == "gzip" and raw:
                raw = gzip.decompress(raw)
            truncated = len(raw) > MAX_BODY
            raw = raw[:MAX_BODY]
            return {
                "status": response.status,
                "reason": response.reason,
                "headers": {k.lower(): v for k, v in response.headers.items()},
                "body": raw,
                "truncated": truncated,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_BODY + 1) if method != "HEAD" else b""
        if exc.headers.get("Content-Encoding", "").lower() == "gzip" and raw:
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        return {
            "status": exc.code,
            "reason": exc.reason,
            "headers": {k.lower(): v for k, v in exc.headers.items()},
            "body": raw[:MAX_BODY],
            "truncated": len(raw) > MAX_BODY,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": None,
            "reason": None,
            "headers": {},
            "body": b"",
            "truncated": False,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }


def walk(obj: Any, path: str = "$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield f"{path}.{key}", key, value
            yield from walk(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            yield from walk(value, f"{path}[{idx}]")


def summarize_json(data: Any) -> dict[str, Any]:
    keys = Counter()
    pii_keys: list[str] = []
    pii_values: list[dict[str, str]] = []
    coordinates: list[tuple[float, float]] = []
    timestamps: list[str] = []
    identifiers: list[str] = []

    for path, key, value in walk(data):
        keys[key] += 1
        if PII_KEY.search(str(key)):
            pii_keys.append(path)
        if isinstance(value, str):
            if EMAIL.search(value):
                pii_values.append({"path": path, "type": "email", "value_hash": hashlib.sha256(value.encode()).hexdigest()[:12]})
            if PHONE.search(value):
                pii_values.append({"path": path, "type": "phone", "value_hash": hashlib.sha256(value.encode()).hexdigest()[:12]})
            if re.match(r"^\d{4}-\d{2}-\d{2}T", value):
                timestamps.append(value)
            if key.lower() in {"id", "pkey", "report_id", "card_id", "image_id"}:
                identifiers.append(value)
        if key.lower() in {"coordinates", "location"} and isinstance(value, list):
            candidate = value
            if candidate and isinstance(candidate[0], list):
                candidate = candidate[0]
            if len(candidate) >= 2 and all(isinstance(x, (int, float)) for x in candidate[:2]):
                coordinates.append((float(candidate[0]), float(candidate[1])))

    future_timestamps: list[str] = []
    stale_timestamps: list[str] = []
    for value in timestamps:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            if parsed > NOW + dt.timedelta(minutes=5):
                future_timestamps.append(value)
            if parsed < NOW - dt.timedelta(days=8):
                stale_timestamps.append(value)
        except ValueError:
            pass

    invalid_coords = [pair for pair in coordinates if not (-180 <= pair[0] <= 180 and -90 <= pair[1] <= 90)]
    exact_coordinate_count = sum(1 for pair in coordinates if any(abs(x - round(x, 3)) > 1e-9 for x in pair))
    return {
        "top_keys": keys.most_common(80),
        "pii_key_paths": sorted(set(pii_keys))[:200],
        "pii_value_hashes": pii_values[:100],
        "coordinate_count": len(coordinates),
        "invalid_coordinates": invalid_coords[:20],
        "coordinates_with_more_than_3_decimal_precision": exact_coordinate_count,
        "timestamp_count": len(timestamps),
        "future_timestamps": future_timestamps[:20],
        "timestamps_older_than_8_days": stale_timestamps[:20],
        "identifier_count": len(identifiers),
        "duplicate_identifier_count": len(identifiers) - len(set(identifiers)),
    }


def main() -> None:
    results: list[dict[str, Any]] = []
    parsed_payloads: dict[str, Any] = {}
    for item in CASES:
        base = BASES[0] if item["base"] == "api" else BASES[1]
        url = base + item["path"]
        response = request(url, item["method"])
        body = response.pop("body")
        text = body.decode("utf-8", errors="replace")
        content_type = response["headers"].get("content-type", "")
        parsed = None
        parse_error = None
        if body and ("json" in content_type.lower() or text.lstrip().startswith(("{", "["))):
            try:
                parsed = json.loads(text)
            except Exception as exc:  # noqa: BLE001
                parse_error = f"{type(exc).__name__}: {exc}"

        header_subset = {name: response["headers"].get(name) for name in SECURITY_HEADERS}
        stack_trace_markers = any(marker in text.lower() for marker in ["traceback", "stack trace", "at module.", "node_modules/", "syntaxerror:", "referenceerror:"])
        result = {
            **item,
            "url": url,
            **response,
            "content_type": content_type,
            "content_length_observed": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest() if body else None,
            "parse_error": parse_error,
            "json_type": type(parsed).__name__ if parsed is not None else None,
            "header_subset": header_subset,
            "stack_trace_marker": stack_trace_markers,
            "body_preview": text[:800].replace("\r", ""),
            "json_summary": summarize_json(parsed) if parsed is not None else None,
        }
        results.append(result)
        if parsed is not None and item["id"] in {"API-001", "API-004", "API-005", "API-031", "API-032", "API-033", "API-034", "API-035", "API-036", "API-046"}:
            parsed_payloads[item["id"]] = parsed
        time.sleep(DELAY_SECONDS)

    # Cross-response consistency checks.
    cross_checks: list[dict[str, Any]] = []
    by_id = {r["id"]: r for r in results}
    for left, right, label in [
        ("API-001", "API-002", "default vs explicit JSON"),
        ("API-004", "API-005", "TopoJSON vs GeoJSON"),
        ("API-007", "API-052", "one-hour baseline vs combined filters"),
        ("API-007", "API-046", "api host vs data host"),
    ]:
        a, b = by_id[left], by_id[right]
        cross_checks.append({
            "label": label,
            "left": left,
            "right": right,
            "same_status": a["status"] == b["status"],
            "same_body_hash": a["body_sha256"] == b["body_sha256"],
            "left_status": a["status"],
            "right_status": b["status"],
            "left_type": a["content_type"],
            "right_type": b["content_type"],
        })

    # Write a sanitized result set; no full production payload is persisted.
    (OUT / "api-audit-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "api-cross-checks.json").write_text(json.dumps(cross_checks, ensure_ascii=False, indent=2), encoding="utf-8")

    with (OUT / "api-audit-results.csv").open("w", encoding="utf-8", newline="") as f:
        fields = ["id", "base", "method", "path", "expected", "status", "elapsed_ms", "content_type", "content_length_observed", "truncated", "error", "parse_error", "stack_trace_marker", "body_sha256"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k) for k in fields})

    status_counts = Counter(str(r["status"]) for r in results)
    missing_security = defaultdict(int)
    for r in results:
        for name, value in r["header_subset"].items():
            if not value:
                missing_security[name] += 1
    summary = {
        "case_count": len(results),
        "methods": Counter(r["method"] for r in results),
        "status_counts": status_counts,
        "error_count": sum(1 for r in results if r["error"]),
        "parse_error_count": sum(1 for r in results if r["parse_error"]),
        "stack_trace_response_count": sum(1 for r in results if r["stack_trace_marker"]),
        "missing_security_header_counts": dict(missing_security),
        "read_only_guarantee": "GET/HEAD/OPTIONS only; no authenticated or mutation requests",
    }
    (OUT / "api-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=dict))


if __name__ == "__main__":
    main()
