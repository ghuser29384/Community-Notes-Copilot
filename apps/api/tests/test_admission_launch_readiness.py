from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models.records import NotesWrittenSnapshot
from app.services.admission import AdmissionDashboardService
from app.services.costs import CostLedger
from app.services.launch_readiness import LaunchReadyAppState
from app.settings import Settings
from app.x_client.community_notes import LiveXCommunityNotesClient
from app.x_client.oauth import oauth1_authorization_header


def note(index: int, *, claim: str = "high", url: str = "high", harassment: str = "high") -> NotesWrittenSnapshot:
    return NotesWrittenSnapshot(
        id=f"id-{index}",
        note_id=f"note-{index}",
        candidate_id=f"candidate-{index}",
        created_at=f"2026-07-{(index % 28) + 1:02d}T00:00:00+00:00",
        crh=False,
        crnh=False,
        nmr=True,
        claim_opinion=claim,
        url_validity=url,
        harassment_abuse=harassment,
        helpfulness="unknown",
    )


class AdmissionLaunchReadinessTests(unittest.TestCase):
    def test_admission_requires_complete_fifty_note_window(self) -> None:
        result = AdmissionDashboardService(Settings()).compute([note(index) for index in range(49)])
        self.assertFalse(result.eligible_boolean)
        self.assertIn("Admission window incomplete: 49/50 test-mode notes", result.blockers)

    def test_admission_uses_most_recent_fifty(self) -> None:
        notes = [note(index) for index in range(1, 51)]
        notes.append(
            NotesWrittenSnapshot(
                id="old-bad",
                note_id="old-bad",
                candidate_id="old-bad",
                created_at="2020-01-01T00:00:00+00:00",
                crh=False,
                crnh=True,
                nmr=False,
                claim_opinion="low",
                url_validity="low",
                harassment_abuse="low",
                helpfulness="low",
            )
        )
        result = AdmissionDashboardService(Settings()).compute(notes)
        self.assertTrue(result.eligible_boolean)
        self.assertNotIn("old-bad", result.raw_inputs["window_note_ids"])

    def test_oauth1_header_is_deterministic_and_query_order_independent(self) -> None:
        kwargs = {
            "consumer_key": "key",
            "consumer_secret": "secret",
            "access_token": "token",
            "access_token_secret": "token-secret",
            "nonce": "fixed-nonce",
            "timestamp": 1_700_000_000,
        }
        first = oauth1_authorization_header("GET", "https://api.x.com/2/test?b=2&a=1", **kwargs)
        second = oauth1_authorization_header("GET", "https://api.x.com/2/test?a=1&b=2", **kwargs)
        self.assertEqual(first, second)
        self.assertIn('oauth_signature_method="HMAC-SHA1"', first)
        self.assertIn('oauth_consumer_key="key"', first)

    def test_auth_mode_auto_prefers_complete_oauth1_credentials(self) -> None:
        settings = Settings(
            x_auth_mode="auto",
            x_api_key="key",
            x_api_key_secret="secret",
            x_access_token="token",
            x_access_token_secret="token-secret",
            x_bearer_token="oauth2-token",
        )
        self.assertEqual(settings.resolved_x_auth_mode(), "oauth1")
        self.assertTrue(settings.x_live_credentials_configured())

    def test_live_notes_written_requests_test_fields_and_merges_evaluator_rows(self) -> None:
        settings = Settings(
            x_provider="live",
            x_auth_mode="oauth2",
            allow_live_x_api=True,
            x_bearer_token="user-token",
        )
        client = LiveXCommunityNotesClient(settings, CostLedger(settings))
        response = {
            "data": [
                {
                    "id": "note-1",
                    "post_id": "post-1",
                    "test_result": {"evaluator_type": "ClaimOpinion", "evaluator_score_bucket": "high"},
                },
                {
                    "id": "note-1",
                    "post_id": "post-1",
                    "test_result": {"evaluator_type": "UrlValidity", "evaluator_score_bucket": "high"},
                },
                {
                    "id": "note-1",
                    "post_id": "post-1",
                    "test_result": {"evaluator_type": "HarassmentAbuse", "evaluator_score_bucket": "high"},
                },
            ],
            "meta": {"result_count": 3},
        }
        with patch("app.x_client.community_notes.request_json", return_value=response) as request:
            result = client.notes_written(test_mode=True)
        url = request.call_args.args[1]
        self.assertIn("test_mode=true", url)
        self.assertIn("note.fields=", url)
        self.assertEqual(len(result["notes"]), 1)
        parsed = result["notes"][0]
        self.assertEqual(parsed["claim_opinion"], "high")
        self.assertEqual(parsed["url_validity"], "high")
        self.assertEqual(parsed["harassment_abuse"], "high")

    def test_exact_approval_binds_classification_and_write_payload(self) -> None:
        state = LaunchReadyAppState(Settings())
        state.seed_history()
        candidate = next(item for item in state.sync_eligible_posts() if "Norway" in item.text)
        state.analyze_candidate(candidate.id)
        state.retrieve_evidence(candidate.id)
        draft = state.generate_drafts(candidate.id)[0]
        state.critique_draft(draft.id)
        state.evaluate_x(draft.id)
        approved = state.approve_draft(
            draft.id,
            classification="misinformed_or_potentially_misleading",
            misleading_tags=["factual_error"],
        )
        metadata = approved.approval_record["submission_metadata"]
        self.assertEqual(metadata["classification"], "misinformed_or_potentially_misleading")
        self.assertEqual(metadata["misleading_tags"], ["factual_error"])
        submission, gate = state.submit_draft(draft.id, test_mode=True)
        self.assertTrue(gate.can_submit)
        self.assertIsNotNone(submission)
        self.assertEqual(submission.x_response["info"]["classification"], "misinformed_or_potentially_misleading")
        self.assertEqual(submission.x_response["info"]["misleading_tags"], ["factual_error"])


if __name__ == "__main__":
    unittest.main()
