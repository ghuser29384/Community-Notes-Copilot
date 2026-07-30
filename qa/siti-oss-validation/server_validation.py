#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import csv
import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
import requests

BASE_URL = os.environ.get("SITI_SERVER_URL", "http://127.0.0.1:8001").rstrip("/")
OUT = Path(os.environ.get("SITI_VALIDATION_OUT", "artifacts/server-validation"))
OUT.mkdir(parents=True, exist_ok=True)
DB = {
    "host": os.environ.get("PGHOST", "127.0.0.1"),
    "port": int(os.environ.get("PGPORT", "5432")),
    "user": os.environ.get("PGUSER", "postgres"),
    "password": os.environ.get("PGPASSWORD", "postgres"),
    "dbname": os.environ.get("PGDATABASE", "cognicity_validation"),
}
UA = "SitiOSS-Authorized-Local-Validation/2026-07-30"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = SESSION.request(method, BASE_URL + path, timeout=30, **kwargs)
        elapsed = (time.perf_counter() - started) * 1000
        try:
            body: Any = response.json()
        except Exception:
            body = response.text[:2000]
        return {
            "method": method,
            "path": path,
            "status": response.status_code,
            "elapsed_ms": round(elapsed, 2),
            "headers": {k.lower(): v for k, v in response.headers.items()},
            "body": body,
        }
    except Exception as exc:
        return {
            "method": method,
            "path": path,
            "status": None,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": repr(exc),
        }


def create_card(username: str, network: str = "twitter") -> str:
    result = request(
        "POST",
        "/cards",
        json={"username": username, "network": network, "language": "en", "network_data": {}},
    )
    if result["status"] != 200:
        raise RuntimeError(f"create card failed: {result}")
    return result["body"]["cardId"]


def flood_payload(text: str) -> dict[str, Any]:
    return {
        "disaster_type": "flood",
        "partnerCode": "",
        "tweetID": "",
        "sub_submission": False,
        "card_data": {"report_type": "flood", "flood_depth": 44},
        "text": text,
        "image_url": "",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "location": {"lat": -6.1754, "lng": 106.8272},
    }


def db_query(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg2.connect(**DB) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            try:
                return cursor.fetchall()
            except psycopg2.ProgrammingError:
                return []


def test_duplicate_sequential() -> dict[str, Any]:
    card = create_card("audit-sequential-duplicate")
    payload = flood_payload("SITI local sequential duplicate validation")
    first = request("PUT", f"/cards/{card}", json=payload)
    second = request("PUT", f"/cards/{card}", json=payload)
    count = db_query("SELECT count(*) FROM grasp.reports WHERE card_id=%s", (card,))[0][0]
    logs = db_query("SELECT event_type, count(*) FROM grasp.log WHERE card_id=%s GROUP BY event_type ORDER BY event_type", (card,))
    return {"card_id": card, "first": first, "second": second, "report_row_count": count, "log_counts": logs}


def test_duplicate_concurrent(workers: int = 25) -> dict[str, Any]:
    card = create_card("audit-concurrent-duplicate")
    payload = flood_payload("SITI local concurrent duplicate validation")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(request, "PUT", f"/cards/{card}", json=payload) for _ in range(workers)]
        results = [future.result() for future in futures]
    report_rows = db_query("SELECT count(*) FROM grasp.reports WHERE card_id=%s", (card,))[0][0]
    log_rows = db_query("SELECT event_type, count(*) FROM grasp.log WHERE card_id=%s GROUP BY event_type ORDER BY event_type", (card,))
    return {
        "card_id": card,
        "attempts": workers,
        "status_counts": dict(Counter(str(item.get("status")) for item in results)),
        "latency_ms": {
            "p50": percentile([item["elapsed_ms"] for item in results], 0.5),
            "p95": percentile([item["elapsed_ms"] for item in results], 0.95),
            "max": max(item["elapsed_ms"] for item in results),
        },
        "report_row_count": report_rows,
        "log_counts": log_rows,
        "sample_results": results[:8],
    }


def test_local_read_load(total: int = 2000, workers: int = 50) -> dict[str, Any]:
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: request("GET", "/reports?timeperiod=3600"), range(total)))
    wall = time.perf_counter() - started
    latencies = [item["elapsed_ms"] for item in results]
    return {
        "requests": total,
        "concurrency": workers,
        "status_counts": dict(Counter(str(item.get("status")) for item in results)),
        "wall_seconds": round(wall, 3),
        "requests_per_second": round(total / wall, 2) if wall else None,
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies),
        },
    }


def test_local_write_load(total: int = 200, workers: int = 25) -> dict[str, Any]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        cards = list(pool.map(lambda index: create_card(f"audit-write-{index}"), range(total)))
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(request, "PUT", f"/cards/{card}", json=flood_payload(f"write-load-{index}")) for index, card in enumerate(cards)]
        results = [future.result() for future in futures]
    wall = time.perf_counter() - started
    latencies = [item["elapsed_ms"] for item in results]
    rows = db_query("SELECT count(*) FROM grasp.reports WHERE card_id = ANY(%s)", (cards,))[0][0]
    return {
        "requests": total,
        "concurrency": workers,
        "status_counts": dict(Counter(str(item.get("status")) for item in results)),
        "persisted_report_rows": rows,
        "wall_seconds": round(wall, 3),
        "writes_per_second": round(total / wall, 2) if wall else None,
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": max(latencies),
        },
    }


def test_image_preflight() -> dict[str, Any]:
    card = create_card("audit-image-preflight")
    return {
        "card_id": card,
        "declared_jpeg": request("GET", f"/cards/{card}/images", headers={"content-type": "image/jpeg"}),
        "declared_png": request("GET", f"/cards/{card}/images", headers={"content-type": "image/png"}),
        "declared_html": request("GET", f"/cards/{card}/images", headers={"content-type": "text/html"}),
        "declared_audio": request("GET", f"/cards/{card}/images", headers={"content-type": "audio/mpeg"}),
        "missing_content_type": request("GET", f"/cards/{card}/images"),
        "scope_note": "The signed-URL endpoint receives a declared MIME type and card ID, not image bytes, so it cannot content-sniff or strip metadata.",
    }


def test_rem_authorization() -> dict[str, Any]:
    local = db_query("SELECT pkey FROM cognicity.local_areas ORDER BY pkey LIMIT 1")
    if not local:
        raise RuntimeError("no local area row available")
    local_id = local[0][0]
    cases = [
        ("no_auth", request("PUT", f"/floods/{local_id}?username=anonymous-no-auth", json={"state": 2})),
        ("malformed_token", request("PUT", f"/floods/{local_id}?username=malformed", headers={"Authorization": "Bearer not-a-jwt"}, json={"state": 3})),
        ("non_editor_fake_org_a", request("PUT", f"/floods/{local_id}?username=org-a-viewer", headers={"Authorization": "Bearer eyJhbGciOiJub25lIn0.eyJyb2xlIjoidmlld2VyIiwib3JnIjoib3JnLWEifQ."}, json={"state": 4})),
        ("cross_org_b", request("PUT", f"/floods/{local_id}?username=org-b-editor", headers={"Authorization": "Bearer eyJhbGciOiJub25lIn0.eyJyb2xlIjoiZWRpdG9yIiwib3JnIjoib3JnLWIifQ."}, json={"state": 1})),
        ("no_auth_delete", request("DELETE", f"/floods/{local_id}?username=anonymous-delete")),
    ]
    logs = db_query("SELECT username, state, changed FROM cognicity.rem_status_log WHERE local_area=%s ORDER BY changed DESC LIMIT 10", (local_id,))
    state = db_query("SELECT local_area, state, last_updated FROM cognicity.rem_status WHERE local_area=%s", (local_id,))
    return {"local_area_id": local_id, "cases": cases, "recent_audit_log": logs, "current_state": state}


def main() -> None:
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "isolated exact public legacy server and PostGIS schema; no production writes",
        "server_url": BASE_URL,
        "health": request("GET", "/"),
    }
    tests = [
        ("sequential_duplicate", test_duplicate_sequential),
        ("concurrent_duplicate", test_duplicate_concurrent),
        ("image_preflight", test_image_preflight),
        ("rem_authorization", test_rem_authorization),
        ("local_read_load", test_local_read_load),
        ("local_write_load", test_local_write_load),
    ]
    for name, function in tests:
        try:
            result[name] = function()
        except Exception as exc:
            result[name] = {"error": repr(exc)}
    (OUT / "server-validation.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    with (OUT / "server-validation-summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["test", "error", "summary"])
        writer.writeheader()
        for name, _function in tests:
            data = result.get(name, {})
            writer.writerow({"test": name, "error": data.get("error"), "summary": json.dumps(data, default=str)[:4000]})
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
