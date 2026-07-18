from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from app.fixtures import fixture_eligible_posts, fixture_notes_written
from app.models.records import XEvaluationResult, new_id, sha256_text
from app.services.costs import CostLedger
from app.services.providers import request_json
from app.settings import Settings
from app.x_client.oauth import oauth1_authorization_header, refresh_oauth2_user_access_token


class XCommunityNotesClient(Protocol):
    def search_posts_eligible_for_notes(self, test_mode: bool, max_results: int, feed_lang: str = "en", feed_size: str = "small") -> dict:
        ...

    def evaluate_note(self, post_id: str, note_text: str) -> XEvaluationResult:
        ...

    def write_note(self, post_id: str, note_text: str, test_mode: bool, info: dict | None = None) -> dict:
        ...

    def notes_written(self, since_id: str | None = None, max_results: int = 100, test_mode: bool = True) -> dict:
        ...

    def get_usage(self) -> dict:
        ...


MISLEADING_CLASSIFICATION = "misinformed_or_potentially_misleading"
NOT_MISLEADING_CLASSIFICATION = "not_misleading"
ALLOWED_CLASSIFICATIONS = {MISLEADING_CLASSIFICATION, NOT_MISLEADING_CLASSIFICATION}
ALLOWED_MISLEADING_TAGS = {
    "disputed_claim_as_fact",
    "factual_error",
    "manipulated_media",
    "misinterpreted_satire",
    "missing_important_context",
    "outdated_information",
    "other",
}


def _validated_submission_info(info: dict | None) -> dict[str, Any]:
    raw = dict(info or {})
    classification = str(raw.get("classification") or "").strip().lower()
    tags = sorted({str(item).strip() for item in raw.get("misleading_tags", []) if str(item).strip()})
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise PermissionError("write_note requires an operator-approved Community Notes classification")
    unknown_tags = sorted(set(tags) - ALLOWED_MISLEADING_TAGS)
    if unknown_tags:
        raise PermissionError(f"Unsupported misleading tags: {', '.join(unknown_tags)}")
    if classification == MISLEADING_CLASSIFICATION and not tags:
        raise PermissionError("Misleading classification requires at least one misleading tag")
    if classification == NOT_MISLEADING_CLASSIFICATION and tags:
        raise PermissionError("not_misleading classification must not include misleading tags")
    return {
        "classification": classification,
        "misleading_tags": tags,
        "trustworthy_sources": bool(raw.get("trustworthy_sources", True)),
        "is_media_note": bool(raw.get("is_media_note", False)),
    }


@dataclass
class FixtureXCommunityNotesClient:
    settings: Settings
    cost_ledger: CostLedger

    def search_posts_eligible_for_notes(self, test_mode: bool, max_results: int, feed_lang: str = "en", feed_size: str = "small") -> dict:
        self.cost_ledger.log("x_fixture", "posts_eligible_for_notes", 0.001, "eligible-feed", {"test_mode": test_mode, "feed_size": feed_size})
        posts = [post for post in fixture_eligible_posts() if post.get("lang", "en") == feed_lang]
        return {
            "test_mode": test_mode,
            "feed_lang": feed_lang,
            "feed_size": feed_size,
            "posts": posts[:max_results],
        }

    def evaluate_note(self, post_id: str, note_text: str) -> XEvaluationResult:
        self.cost_ledger.log("x_fixture", "evaluate_note", 0.002, post_id)
        lowered = note_text.lower()
        claim_score = 0.92
        if "official" not in lowered and "cdc" not in lowered and "iea" not in lowered and "norway" not in lowered:
            claim_score = 0.42
        return XEvaluationResult(
            id=new_id(),
            draft_id="",
            candidate_id="",
            post_id=post_id,
            exact_text_hash=sha256_text(note_text),
            claim_opinion_score=claim_score,
            url_validity_score=0.99,
            harassment_abuse_score=0.99,
            helpfulness_score=0.86,
            raw={
                "fixture": True,
                "score_labels": {
                    "ClaimOpinion": "high" if claim_score >= 0.75 else "medium",
                    "UrlValidity": "high",
                    "HarassmentAbuse": "high",
                },
            },
        )

    def write_note(self, post_id: str, note_text: str, test_mode: bool, info: dict | None = None) -> dict:
        if self.settings.emergency_stop_external_writes:
            raise PermissionError("Emergency stop blocks all external writes")
        self.cost_ledger.log("x_fixture", "write_note", 0.003, post_id, {"test_mode": test_mode})
        if not test_mode and not self.settings.allow_non_test_mode_write:
            raise PermissionError("Non-test write blocked by ALLOW_NON_TEST_MODE_WRITE=false")
        fixture_info = dict(info or {})
        fixture_info.setdefault("classification", MISLEADING_CLASSIFICATION)
        if fixture_info["classification"] == MISLEADING_CLASSIFICATION and not fixture_info.get("misleading_tags"):
            fixture_info["misleading_tags"] = ["other"]
        submission_info = _validated_submission_info(fixture_info)
        return {
            "id": f"fixture-write-{new_id()}",
            "post_id": post_id,
            "test_mode": test_mode,
            "accepted": True,
            "info": submission_info,
        }

    def notes_written(self, since_id: str | None = None, max_results: int = 100, test_mode: bool = True) -> dict:
        self.cost_ledger.log("x_fixture", "notes_written", 0.001, "notes-written", {"since_id": since_id, "test_mode": test_mode})
        return {"notes": fixture_notes_written()[:max_results], "since_id": since_id, "test_mode": test_mode}

    def get_usage(self) -> dict:
        return {
            "usage_api": {
                "source": "fixture_usage_api",
                "daily_post_consumption": len(self.cost_ledger.entries),
                "monthly_post_consumption": len(self.cost_ledger.entries),
                "deduplication_soft_guarantee": True,
            }
        }


def _score_bucket(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "high": "high",
        "medium": "medium",
        "low": "low",
        "pass": "high",
        "passed": "high",
    }
    return aliases.get(normalized, "unknown")


def _evaluator_field(value: Any) -> str | None:
    normalized = "".join(character for character in str(value or "").lower() if character.isalnum())
    if "claim" in normalized and "opinion" in normalized:
        return "claim_opinion"
    if "url" in normalized and ("valid" in normalized or "source" in normalized):
        return "url_validity"
    if "harassment" in normalized or "abuse" in normalized:
        return "harassment_abuse"
    if "helpful" in normalized:
        return "helpfulness"
    return None


def _flatten_test_results(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    if "evaluator_type" in value or "evaluator_score_bucket" in value:
        return [value]
    entries: list[dict[str, Any]] = []
    for key, item in value.items():
        if isinstance(item, dict):
            entries.append({"evaluator_type": item.get("evaluator_type", key), **item})
        elif isinstance(item, (str, int, float)):
            entries.append({"evaluator_type": key, "evaluator_score_bucket": item})
        elif isinstance(item, list):
            entries.extend(_flatten_test_results(item))
    return entries


def _test_result_labels(value: Any) -> dict[str, str]:
    labels = {
        "claim_opinion": "unknown",
        "url_validity": "unknown",
        "harassment_abuse": "unknown",
        "helpfulness": "unknown",
    }
    for item in _flatten_test_results(value):
        field = _evaluator_field(item.get("evaluator_type") or item.get("type") or item.get("name"))
        if not field:
            continue
        labels[field] = _score_bucket(
            item.get("evaluator_score_bucket")
            or item.get("score_bucket")
            or item.get("bucket")
            or item.get("score")
        )
    return labels


def _rating_status(item: dict[str, Any]) -> tuple[bool, bool, bool, str]:
    status = str(item.get("status") or "").strip().lower().replace("-", "_").replace(" ", "_")
    crh = status in {"crh", "currently_rated_helpful", "helpful"}
    crnh = status in {"crnh", "currently_rated_not_helpful", "not_helpful"}
    nmr = status in {"nmr", "needs_more_ratings"}
    helpfulness = "high" if crh else "low" if crnh else "unknown"
    return crh, crnh, nmr, helpfulness


@dataclass
class LiveXCommunityNotesClient:
    settings: Settings
    cost_ledger: CostLedger

    def __post_init__(self) -> None:
        self._access_token = self.settings.x_bearer_token
        self._refresh_token = self.settings.x_oauth2_refresh_token

    def _disabled(self) -> None:
        if not self.settings.allow_live_x_api:
            raise PermissionError("Live X API calls are disabled by default. Set ALLOW_LIVE_X_API=true to enable.")
        resolved_mode = self.settings.resolved_x_auth_mode()
        if resolved_mode == "invalid":
            raise PermissionError("X_AUTH_MODE must be one of auto, oauth1, or oauth2.")
        if not self.settings.x_live_credentials_configured():
            raise PermissionError(
                "A user-context X credential is required: configure OAuth 1.0a API/access-token credentials, "
                "or an OAuth 2.0 user access/refresh token."
            )

    def _access_token_for_request(self) -> str:
        if self.settings.x_oauth2_refresh_configured() and (not self._access_token or self._access_token == self.settings.x_bearer_token):
            token = refresh_oauth2_user_access_token(
                self.settings.x_oauth2_client_id,
                self.settings.x_oauth2_client_secret,
                self._refresh_token or self.settings.x_oauth2_refresh_token,
            )
            self._access_token = token.access_token
            self._refresh_token = token.refresh_token or self._refresh_token
        if self._access_token:
            return self._access_token
        raise PermissionError("An OAuth 2.0 user access token or refresh-token configuration is required.")

    def _headers(self, method: str = "GET", url: str = "https://api.x.com/") -> dict[str, str]:
        mode = self.settings.resolved_x_auth_mode()
        if mode == "oauth1":
            return {
                "Authorization": oauth1_authorization_header(
                    method,
                    url,
                    self.settings.x_api_key,
                    self.settings.x_api_key_secret,
                    self.settings.x_access_token,
                    self.settings.x_access_token_secret,
                )
            }
        if mode == "oauth2":
            return {"Authorization": f"Bearer {self._access_token_for_request()}"}
        if mode == "invalid":
            raise PermissionError("X_AUTH_MODE must be one of auto, oauth1, or oauth2.")
        raise PermissionError("No configured X user-context authentication mode is available.")

    def _normalize_post(self, item: dict) -> dict:
        return {
            "x_post_id": str(item.get("id") or item.get("x_post_id")),
            "text": item.get("text", ""),
            "author_id": str(item.get("author_id", "unknown")),
            "lang": item.get("lang", "en"),
            "note_tweet": item.get("note_tweet", {}),
            "referenced_posts": item.get("referenced_posts", []),
            "quoted_posts": item.get("quoted_posts", []),
            "replied_to_posts": item.get("replied_to_posts", []),
            "media_metadata": item.get("media_metadata", []),
            "suggested_source_links_with_counts": item.get("suggested_source_links_with_counts", []),
            "note_request_suggestions": item.get("note_request_suggestions", []),
            "raw_x_api": item,
        }

    def search_posts_eligible_for_notes(self, test_mode: bool, max_results: int, feed_lang: str = "en", feed_size: str = "small") -> dict:
        self._disabled()
        params = urlencode(
            {
                "test_mode": str(test_mode).lower(),
                "max_results": max(1, min(max_results, 100)),
                "post_selection": f"feed_size:{feed_size},feed_lang:{feed_lang}",
                "tweet.fields": "author_id,created_at,lang,note_tweet,media_metadata,note_request_suggestions,suggested_source_links_with_counts,text,referenced_tweets",
            }
        )
        url = f"https://api.x.com/2/notes/search/posts_eligible_for_notes?{params}"
        payload = request_json("GET", url, headers=self._headers("GET", url))
        self.cost_ledger.log("x_live", "posts_eligible_for_notes", 0.0, "eligible-feed", {"test_mode": test_mode, "feed_size": feed_size})
        return {
            "test_mode": test_mode,
            "feed_lang": feed_lang,
            "feed_size": feed_size,
            "posts": [self._normalize_post(item) for item in payload.get("data", [])],
            "meta": payload.get("meta", {}),
            "errors": payload.get("errors", []),
        }

    def evaluate_note(self, post_id: str, note_text: str) -> XEvaluationResult:
        self._disabled()
        url = "https://api.x.com/2/evaluate_note"
        payload = request_json(
            "POST",
            url,
            headers=self._headers("POST", url),
            body={"post_id": post_id, "note_text": note_text},
        )
        data = payload.get("data", {})
        score = float(data.get("claim_opinion_score", 0.0))
        self.cost_ledger.log("x_live", "evaluate_note", 0.0, post_id)
        return XEvaluationResult(
            id=new_id(),
            draft_id="",
            candidate_id="",
            post_id=post_id,
            exact_text_hash=sha256_text(note_text),
            claim_opinion_score=score,
            url_validity_score=float(data.get("url_validity_score", 0.0) or 0.0),
            harassment_abuse_score=float(data.get("harassment_abuse_score", 0.0) or 0.0),
            helpfulness_score=float(data.get("helpfulness_score", score) or score),
            raw=payload,
        )

    def write_note(self, post_id: str, note_text: str, test_mode: bool, info: dict | None = None) -> dict:
        self._disabled()
        if self.settings.emergency_stop_external_writes:
            raise PermissionError("Emergency stop blocks all external writes")
        if not self.settings.allow_live_x_write:
            raise PermissionError("Live X write_note is blocked by ALLOW_LIVE_X_WRITE=false")
        if not test_mode and not self.settings.allow_non_test_mode_write:
            raise PermissionError("Non-test write blocked by ALLOW_NON_TEST_MODE_WRITE=false")
        submission_info = _validated_submission_info(info)
        url = "https://api.x.com/2/notes"
        payload = request_json(
            "POST",
            url,
            headers=self._headers("POST", url),
            body={
                "post_id": post_id,
                "test_mode": test_mode,
                "info": {
                    "text": note_text,
                    "classification": submission_info["classification"],
                    "misleading_tags": submission_info["misleading_tags"],
                    "trustworthy_sources": submission_info["trustworthy_sources"],
                    "is_media_note": submission_info["is_media_note"],
                },
            },
        )
        self.cost_ledger.log("x_live", "write_note", 0.0, post_id, {"test_mode": test_mode})
        return payload

    def notes_written(self, since_id: str | None = None, max_results: int = 100, test_mode: bool = True) -> dict:
        self._disabled()
        params = {
            "test_mode": str(test_mode).lower(),
            "max_results": max(1, min(max_results, 100)),
            "note.fields": "id,info,scoring_status,status,test_result",
        }
        if since_id:
            params["since_id"] = since_id
        url = f"https://api.x.com/2/notes/search/notes_written?{urlencode(params)}"
        payload = request_json("GET", url, headers=self._headers("GET", url))
        self.cost_ledger.log("x_live", "notes_written", 0.0, "notes-written", {"since_id": since_id, "test_mode": test_mode})
        notes_by_id: dict[str, dict[str, Any]] = {}
        note_order: list[str] = []
        for item in payload.get("data", []):
            scoring = item.get("scoring_status", {}) or {}
            info = item.get("info", {}) or {}
            labels = _test_result_labels(item.get("test_result"))
            crh, crnh, nmr, rating_helpfulness = _rating_status(item)
            if labels["helpfulness"] == "unknown":
                labels["helpfulness"] = rating_helpfulness
            note_id = str(item.get("id", ""))
            if note_id not in notes_by_id:
                note_order.append(note_id)
                notes_by_id[note_id] = {
                    "id": new_id(),
                    "note_id": note_id,
                    "candidate_id": str(item.get("post_id") or info.get("post_id") or ""),
                    "created_at": str(item.get("created_at") or info.get("created_at") or ""),
                    "crh": crh,
                    "crnh": crnh,
                    "nmr": nmr,
                    "claim_opinion": "unknown",
                    "url_validity": "unknown",
                    "harassment_abuse": "unknown",
                    "helpfulness": "unknown",
                    "test_result": "unknown",
                    "scoring_status": "has_access" if scoring.get("has_access") else str(item.get("status") or "unknown"),
                }
            current = notes_by_id[note_id]
            current["crh"] = current["crh"] or crh
            current["crnh"] = current["crnh"] or crnh
            current["nmr"] = current["nmr"] or nmr
            for field in ("claim_opinion", "url_validity", "harassment_abuse", "helpfulness"):
                if labels[field] != "unknown":
                    current[field] = labels[field]
            if any(current[field] != "unknown" for field in ("claim_opinion", "url_validity", "harassment_abuse")):
                current["test_result"] = "scored"
        notes = [notes_by_id[note_id] for note_id in note_order]
        return {"notes": notes, "meta": payload.get("meta", {}), "errors": payload.get("errors", []), "test_mode": test_mode}

    def get_usage(self) -> dict:
        self._disabled()
        url = "https://api.x.com/2/usage/tweets?days=7"
        payload = request_json("GET", url, headers=self._headers("GET", url))
        data = payload.get("data", {})
        project_usage = int(data.get("project_usage") or 0)
        return {
            "usage_api": {
                "source": "x_usage_api",
                "daily_post_consumption": project_usage,
                "monthly_post_consumption": project_usage,
                "deduplication_soft_guarantee": True,
                "raw": payload,
            }
        }
