from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.fixtures import fixture_eligible_posts, fixture_notes_written
from app.models.records import XEvaluationResult, new_id, sha256_text
from app.services.costs import CostLedger
from app.settings import Settings


class XCommunityNotesClient(Protocol):
    def search_posts_eligible_for_notes(self, test_mode: bool, max_results: int, feed_lang: str = "en", feed_size: str = "small") -> dict:
        ...

    def evaluate_note(self, post_id: str, note_text: str) -> XEvaluationResult:
        ...

    def write_note(self, post_id: str, note_text: str, test_mode: bool, info: dict | None = None) -> dict:
        ...

    def notes_written(self, since_id: str | None = None, max_results: int = 100) -> dict:
        ...

    def get_usage(self) -> dict:
        ...


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
        self.cost_ledger.log("x_fixture", "write_note", 0.003, post_id, {"test_mode": test_mode})
        if not test_mode and not self.settings.allow_non_test_mode_write:
            raise PermissionError("Non-test write blocked by ALLOW_NON_TEST_MODE_WRITE=false")
        return {
            "id": f"fixture-write-{new_id()}",
            "post_id": post_id,
            "test_mode": test_mode,
            "accepted": True,
            "info": info or {},
        }

    def notes_written(self, since_id: str | None = None, max_results: int = 100) -> dict:
        self.cost_ledger.log("x_fixture", "notes_written", 0.001, "notes-written", {"since_id": since_id})
        return {"notes": fixture_notes_written()[:max_results], "since_id": since_id}

    def get_usage(self) -> dict:
        return {
            "usage_api": {
                "source": "fixture_usage_api",
                "daily_post_consumption": len(self.cost_ledger.entries),
                "monthly_post_consumption": len(self.cost_ledger.entries),
                "deduplication_soft_guarantee": True,
            }
        }


@dataclass
class LiveXCommunityNotesClient:
    settings: Settings
    cost_ledger: CostLedger

    def _disabled(self) -> None:
        if not self.settings.allow_live_x_api:
            raise PermissionError("Live X API calls are disabled by default. Set ALLOW_LIVE_X_API=true to enable.")

    def search_posts_eligible_for_notes(self, test_mode: bool, max_results: int, feed_lang: str = "en", feed_size: str = "small") -> dict:
        self._disabled()
        raise NotImplementedError("Live X API integration is intentionally behind the safety flag.")

    def evaluate_note(self, post_id: str, note_text: str) -> XEvaluationResult:
        self._disabled()
        raise NotImplementedError("Live X evaluate_note is intentionally behind the safety flag.")

    def write_note(self, post_id: str, note_text: str, test_mode: bool, info: dict | None = None) -> dict:
        self._disabled()
        if not test_mode and not self.settings.allow_non_test_mode_write:
            raise PermissionError("Non-test write blocked by ALLOW_NON_TEST_MODE_WRITE=false")
        raise NotImplementedError("Live X write_note is intentionally behind the safety flag.")

    def notes_written(self, since_id: str | None = None, max_results: int = 100) -> dict:
        self._disabled()
        raise NotImplementedError("Live X notes_written is intentionally behind the safety flag.")

    def get_usage(self) -> dict:
        self._disabled()
        return {"usage_api": {}}
