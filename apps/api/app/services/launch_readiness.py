from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.models.records import CandidatePost, DraftNote, EvidenceCard, sha256_text
from app.services.governance import ExactSubmissionPreviewAndApprovalRecord
from app.services.store import AppState
from app.settings import Settings


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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def normalize_submission_metadata(classification: Any, misleading_tags: Any) -> tuple[dict[str, Any], list[str]]:
    normalized_classification = str(classification or "").strip().lower()
    if isinstance(misleading_tags, str):
        raw_tags = [item.strip() for item in misleading_tags.split(",")]
    elif isinstance(misleading_tags, (list, tuple, set)):
        raw_tags = [str(item).strip() for item in misleading_tags]
    elif misleading_tags is None:
        raw_tags = []
    else:
        raw_tags = [str(misleading_tags).strip()]
    normalized_tags = sorted({item for item in raw_tags if item})

    blockers: list[str] = []
    if normalized_classification not in ALLOWED_CLASSIFICATIONS:
        blockers.append("Operator must select a supported Community Notes classification")
    unknown_tags = sorted(set(normalized_tags) - ALLOWED_MISLEADING_TAGS)
    if unknown_tags:
        blockers.append(f"Unsupported misleading tags: {', '.join(unknown_tags)}")
    if normalized_classification == MISLEADING_CLASSIFICATION and not normalized_tags:
        blockers.append("Misleading classification requires at least one misleading tag")
    if normalized_classification == NOT_MISLEADING_CLASSIFICATION and normalized_tags:
        blockers.append("not_misleading classification must not include misleading tags")

    return {
        "classification": normalized_classification,
        "misleading_tags": normalized_tags,
    }, blockers


@dataclass
class SubmissionMetadataApprovalRecord(ExactSubmissionPreviewAndApprovalRecord):
    """Bind X-required classification metadata into the exact approval hash."""

    @staticmethod
    def _raw_metadata(draft: DraftNote) -> dict[str, Any]:
        record = draft.approval_record or {}
        return dict(record.get("pending_submission_metadata") or record.get("submission_metadata") or {})

    def submission_metadata(self, draft: DraftNote) -> tuple[dict[str, Any], list[str]]:
        raw = self._raw_metadata(draft)
        return normalize_submission_metadata(raw.get("classification"), raw.get("misleading_tags"))

    def gate_input_hash(self, candidate: CandidatePost, draft: DraftNote, cards: list[EvidenceCard], test_mode: bool) -> str:
        base_hash = super().gate_input_hash(candidate, draft, cards, test_mode)
        metadata, blockers = self.submission_metadata(draft)
        return sha256_text(
            _canonical_json(
                {
                    "base_gate_input_hash": base_hash,
                    "submission_metadata": metadata,
                    "submission_metadata_blockers": blockers,
                }
            )
        )

    def preview(
        self,
        candidate: CandidatePost,
        draft: DraftNote,
        cards: list[EvidenceCard],
        test_mode: bool,
        gate_snapshot: dict | None = None,
    ) -> dict:
        preview = super().preview(candidate, draft, cards, test_mode, gate_snapshot)
        metadata, blockers = self.submission_metadata(draft)
        payload = dict(preview["api_payload"])
        payload["info"] = {
            **dict(payload.get("info") or {}),
            "classification": metadata["classification"],
            "misleading_tags": metadata["misleading_tags"],
        }
        preview["api_payload"] = payload
        preview["submission_metadata"] = metadata
        preview["payload_hash"] = sha256_text(
            _canonical_json(
                {
                    "payload": payload,
                    "source_urls": preview["source_urls"],
                    "gate_input_hash": preview["gate_input_hash"],
                }
            )
        )
        preview["unresolved_warnings"] = sorted(set(preview.get("unresolved_warnings", []) + blockers))
        return preview

    def approve(
        self,
        candidate: CandidatePost,
        draft: DraftNote,
        cards: list[EvidenceCard],
        test_mode: bool,
        gate_snapshot: dict | None = None,
    ) -> dict:
        _, blockers = self.submission_metadata(draft)
        if blockers:
            raise PermissionError("; ".join(blockers))
        return super().approve(candidate, draft, cards, test_mode, gate_snapshot)

    def validate(self, candidate: CandidatePost, draft: DraftNote, cards: list[EvidenceCard], test_mode: bool) -> dict:
        result = super().validate(candidate, draft, cards, test_mode)
        _, blockers = self.submission_metadata(draft)
        if blockers:
            result["status"] = "BLOCK"
            result["blockers"] = sorted(set(result.get("blockers", []) + blockers))
        result["submission_metadata"] = self.submission_metadata(draft)[0]
        return result


class SubmissionMetadataXClient:
    """Inject only operator-approved submission metadata into write_note calls."""

    def __init__(self, delegate: Any, state: "LaunchReadyAppState"):
        self.delegate = delegate
        self.state = state

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def write_note(self, post_id: str, note_text: str, test_mode: bool, info: dict | None = None) -> dict:
        outgoing = dict(info or {})
        draft_id = str(outgoing.get("draft_id") or "")
        draft = self.state.drafts.get(draft_id)
        if not draft:
            raise PermissionError("write_note requires a persisted, approved draft_id")
        metadata, blockers = self.state.approval_records.submission_metadata(draft)
        if blockers:
            raise PermissionError("; ".join(blockers))
        candidate = self.state.candidates[draft.candidate_id]
        outgoing.update(metadata)
        outgoing["is_media_note"] = candidate.media_dependency.get("classification") == "media_dependent"
        return self.delegate.write_note(post_id, note_text, test_mode, info=outgoing)


class LaunchReadyAppState(AppState):
    """Production entrypoint with admission-run API contract hardening."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.approval_records = SubmissionMetadataApprovalRecord(settings)
        self.x_client = SubmissionMetadataXClient(self.x_client, self)

    def approve_draft(
        self,
        draft_id: str,
        override_reason: str | None = None,
        classification: str | None = None,
        misleading_tags: list[str] | str | None = None,
    ) -> DraftNote:
        draft = self.drafts[draft_id]
        existing = dict((draft.approval_record or {}).get("submission_metadata") or {})
        selected_classification = classification or existing.get("classification")
        if not selected_classification:
            if self.settings.x_provider == "live":
                raise PermissionError("Operator must explicitly select a Community Notes classification before live approval")
            selected_classification = MISLEADING_CLASSIFICATION
        if misleading_tags is None:
            if selected_classification == NOT_MISLEADING_CLASSIFICATION:
                selected_tags: list[str] | str = []
            elif existing.get("misleading_tags"):
                selected_tags = existing["misleading_tags"]
            elif self.settings.x_provider == "live":
                raise PermissionError("Operator must explicitly select at least one misleading tag before live approval")
            else:
                selected_tags = ["other"]
        else:
            selected_tags = misleading_tags
        metadata, blockers = normalize_submission_metadata(selected_classification, selected_tags)
        if blockers:
            raise PermissionError("; ".join(blockers))
        draft.approval_record = {"pending_submission_metadata": metadata}
        return super().approve_draft(draft_id, override_reason)

    def provider_readiness(self) -> dict:
        readiness = super().provider_readiness()
        readiness["configured_x_auth_mode"] = self.settings.x_auth_mode
        readiness["resolved_x_auth_mode"] = self.settings.resolved_x_auth_mode()
        if not self.settings.x_live_credentials_configured() and self.settings.x_provider == "live":
            readiness["blockers"] = [
                blocker
                if not blocker.startswith("A user-context X credential is required")
                else "A user-context X credential is required: configure OAuth 1.0a API/access-token credentials or OAuth 2.0 user credentials"
                for blocker in readiness["blockers"]
            ]
        return readiness
