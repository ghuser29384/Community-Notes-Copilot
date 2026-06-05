from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app.main import Handler, STATE


PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


def request(path: str, method: str = "GET", body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        raw = response.read().decode("utf-8")
        content_type = response.headers.get("Content-Type", "")
        return json.loads(raw) if "application/json" in content_type else raw


def main() -> int:
    STATE.seed_history()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    try:
        health = request("/api/health")
        assert health["status"] == "ok"
        settings = request("/api/settings")
        assert settings["policy_scope"]["data_use_scope_allowed"] is True
        assert settings["policy_scope"]["operational_evals_scope_allowed"] is True
        assert settings["bot_identity"]["configured"] is True
        synced = request("/api/x/sync-eligible-posts", method="POST", body={"test_mode": True, "max_results": 10})
        candidates = synced["candidates"]
        assert candidates
        candidate = next(item for item in candidates if "Norway" in item["text"])
        candidate_id = candidate["id"]
        claims = request(f"/api/candidates/{candidate_id}/analyze", method="POST", body={})["claims"]
        assert claims and claims[0]["status"] == "CHECKABLE"
        evidence = request(f"/api/candidates/{candidate_id}/retrieve", method="POST", body={})["evidence_cards"]
        assert any(card["approved"] for card in evidence)
        drafts = request(f"/api/candidates/{candidate_id}/drafts", method="POST", body={})["drafts"]
        draft_id = drafts[0]["id"]
        try:
            request(f"/api/drafts/{draft_id}/export")
            raise AssertionError("export without consent should fail")
        except urllib.error.HTTPError as error:
            assert error.code == 403
        exported = request(
            f"/api/drafts/{draft_id}/export?consent_ack=true&consent_actor=operator&consent_reason=manual%20export"
        )
        assert "Express consent actor: operator" in exported
        critique = request(f"/api/drafts/{draft_id}/critique", method="POST", body={})
        assert critique["grounding_pass"] is True
        evaluation = request(f"/api/drafts/{draft_id}/evaluate-x", method="POST", body={})
        assert evaluation["claim_opinion_score"] >= 0.3
        approved = request(f"/api/drafts/{draft_id}/approve", method="POST", body={})
        assert approved["operator_approved"] is True
        submitted = request(f"/api/drafts/{draft_id}/submit", method="POST", body={"test_mode": True})
        assert submitted["submission"]["test_mode"] is True
        assert submitted["gate"]["can_submit"] is True
        costs = request("/api/costs")
        assert costs["summary"]["usage_api_reconciled"] is True
        assert costs["summary"]["developer_console_reconciliation_required"] is True
        dashboard = request("/api/dashboard")
        assert dashboard["queue_summary"]["submissions"] >= 1
        assert dashboard["policy_scope"]["data_use_scope_allowed"] is True
        assert dashboard["bot_identity"]["configured"] is True
        page = request("/")
        assert "Community Notes Ops Copilot" in page
        print("E2E fixture flow passed")
        return 0
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
