from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.models.records import (
    CandidatePost,
    Claim,
    DraftNote,
    EvidenceCard,
    InternalScore,
    WritingLimitSnapshot,
    XEvaluationResult,
    now_iso,
    sha256_text,
    stable_id,
)
from app.services.costs import CostSummary
from app.settings import Settings


def _lower_blob(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            parts.extend(str(item) for item in value.values())
        elif isinstance(value, list):
            for item in value:
                parts.append(_lower_blob(item))
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts).lower()


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(f"{value}T00:00:00+00:00")
    except ValueError:
        return None


@dataclass
class PhasedDeliveryAndComplexityBudget:
    settings: Settings

    def status(self) -> dict:
        live_write_phase = "track_b_test_mode" if not self.settings.allow_non_test_mode_write else "track_b_non_test_enabled"
        return {
            "policy_version": self.settings.governance_policy_version,
            "current_phase": live_write_phase,
            "tracks": {
                "track_a_manual_export": {
                    "enabled": True,
                    "requires_express_consent": self.settings.track_a_requires_express_consent,
                },
                "track_b_api_native": {
                    "read_enabled": self.settings.allow_live_x_api,
                    "test_mode_write_possible": self.settings.allow_live_x_write,
                    "non_test_write_possible": self.settings.allow_live_x_write and self.settings.allow_non_test_mode_write,
                },
            },
            "complexity_budget": {
                "live_search": self.settings.allow_live_search,
                "live_llm": self.settings.allow_live_llm,
                "approved_multimodal_workflow": self.settings.approved_multimodal_workflow_enabled,
                "workers_must_remain_nonblocking": True,
            },
        }


@dataclass
class LatencySLOAndGracefulDegradationService:
    settings: Settings

    def stage_budget(self, stage: str) -> dict:
        budgets = {
            "sync": 6.0,
            "analyze": 8.0,
            "retrieve": 15.0,
            "draft": 12.0,
            "critique": 5.0,
            "evaluate_x": 10.0,
            "submit": 6.0,
        }
        budget = budgets.get(stage, 8.0)
        return {
            "stage": stage,
            "budget_seconds": budget,
            "degradation": "hold_for_operator_if_budget_exceeded",
            "nonblocking_worker_required": True,
        }

    def status(self) -> dict:
        return {
            "slo_version": "latency-slo-v1",
            "stage_budgets": {stage: self.stage_budget(stage)["budget_seconds"] for stage in ["sync", "analyze", "retrieve", "draft", "critique", "evaluate_x", "submit"]},
            "graceful_degradation": "prefer abstain/hold/defer over slow or partial external writes",
        }


@dataclass
class PlatformAdapter:
    settings: Settings

    def from_x_payload(self, candidate: CandidatePost, raw: dict) -> dict:
        return {
            "schema": "PortableContextSchema",
            "schema_version": "2026-06-07",
            "platform": "x",
            "platform_adapter": "XCommunityNotesAdapter",
            "platform_content": {
                "platform_content_id": candidate.x_post_id,
                "author_id": candidate.author_id,
                "text": candidate.text,
                "lang": candidate.lang,
                "created_at": candidate.note_tweet.get("created_at") or raw.get("created_at"),
                "relationships": {
                    "referenced_posts": candidate.referenced_posts,
                    "quoted_posts": candidate.quoted_posts,
                    "replied_to_posts": candidate.replied_to_posts,
                },
                "media": candidate.media_metadata,
                "suggested_source_links_with_counts": candidate.suggested_source_links_with_counts,
                "note_request_suggestions": candidate.note_request_suggestions,
            },
            "x_raw_payload_available": True,
            "platform_raw_payload_fields": sorted(raw.keys()),
        }


class AudienceContextService:
    JURISDICTION_HINTS = {
        "norway": "Norway",
        "norwegian": "Norway",
        "cdc": "United States",
        "centers for disease control": "United States",
        "fda": "United States",
        "city council": "local civic",
        "election": "jurisdiction-specific civic",
    }

    def classify(self, candidate: CandidatePost) -> dict:
        blob = _lower_blob(candidate.text, candidate.referenced_posts, candidate.quoted_posts, candidate.replied_to_posts, candidate.suggested_source_links_with_counts)
        jurisdictions = sorted({label for token, label in self.JURISDICTION_HINTS.items() if token in blob})
        context_sources = []
        if candidate.referenced_posts:
            context_sources.append("referenced_posts")
        if candidate.quoted_posts:
            context_sources.append("quoted_posts")
        if candidate.replied_to_posts:
            context_sources.append("replied_to_posts")
        if candidate.note_request_suggestions:
            context_sources.append("note_request_suggestions")
        return {
            "status": "PASS",
            "feed_lang": candidate.lang,
            "jurisdictions": jurisdictions,
            "context_sources": context_sources,
            "reader_context_notes": "Use localized/current context when claims depend on place, time, or audience assumptions.",
        }

    def gate(self, candidate: CandidatePost) -> dict:
        context = candidate.audience_context or self.classify(candidate)
        high_stakes = candidate.high_stakes or {}
        if high_stakes.get("risk_tier") == "high" and not context.get("jurisdictions"):
            return {
                "status": "HOLD_FOR_OPERATOR",
                "blockers": ["High-stakes claim needs explicit jurisdiction/audience context"],
            }
        return {"status": "PASS", "blockers": []}


@dataclass
class MediaDependencyGate:
    settings: Settings

    def classify(self, candidate: CandidatePost) -> dict:
        blob = _lower_blob(candidate.text, candidate.media_metadata, candidate.referenced_posts, candidate.quoted_posts)
        media_present = bool(candidate.media_metadata)
        media_terms = [
            "this video",
            "video shows",
            "this image",
            "photo shows",
            "screenshot shows",
            "chart shows",
            "in the clip",
            "audio proves",
        ]
        media_dependent = media_present and any(term in blob for term in media_terms)
        if media_dependent and not self.settings.approved_multimodal_workflow_enabled:
            decision = "HOLD_FOR_OPERATOR"
            blockers = ["Media-dependent claim requires approved multimodal review before drafting/submission"]
        else:
            decision = "PASS"
            blockers = []
        return {
            "media_present": media_present,
            "classification": "media_dependent" if media_dependent else ("text_claim_with_media_context" if media_present else "text_only"),
            "approved_multimodal_workflow": self.settings.approved_multimodal_workflow_enabled,
            "decision": decision,
            "blockers": blockers,
            "media_metadata_is_hint_not_proof": True,
        }


class HighStakesDomainRouter:
    DOMAIN_KEYWORDS = {
        "health_medical": ["cdc", "vaccine", "measles", "medical", "disease", "drug", "hospital", "infection"],
        "election_civic": ["election", "ballot", "vote", "voting", "city council", "mayor"],
        "legal_regulatory": ["law", "lawsuit", "court", "regulation", "illegal", "legal"],
        "financial": ["stock", "sec", "bank", "interest rate", "investment", "crypto"],
        "public_safety": ["evacuation", "fire", "police", "emergency", "public safety"],
        "war_crisis": ["war", "missile", "invasion", "ceasefire", "refugee"],
        "identity_sensitive": ["race", "religion", "gender", "immigrant", "ethnicity"],
    }
    AUTHORITATIVE_HINTS = {
        "health_medical": ["cdc", "centers for disease control", "nih", "fda", "who", "health"],
        "election_civic": ["election", "official", "secretary of state", "city"],
        "legal_regulatory": ["court", "agency", "official", "regulator"],
        "financial": ["sec", "federal reserve", "treasury", "official"],
        "public_safety": ["official", "agency", "emergency"],
        "war_crisis": ["united nations", "official", "ministry", "agency"],
        "identity_sensitive": ["official", "peer reviewed", "institutional"],
    }

    def classify(self, candidate: CandidatePost) -> dict:
        blob = _lower_blob(candidate.text, candidate.suggested_source_links_with_counts, candidate.note_request_suggestions)
        domains = sorted(domain for domain, keywords in self.DOMAIN_KEYWORDS.items() if any(keyword in blob for keyword in keywords))
        risk_tier = "high" if domains else "standard"
        return {
            "risk_tier": risk_tier,
            "domains": domains,
            "requires_authoritative_sources": bool(domains),
            "requires_currentness": bool(domains),
            "requires_operator_confirmation": bool(domains),
            "authoritative_evidence_met": not domains,
            "currentness_met": not domains,
            "decision": "PASS" if not domains else "REQUIRE_HIGH_STAKES_REVIEW",
            "blockers": [],
        }

    def evaluate_evidence(self, candidate: CandidatePost, cards: list[EvidenceCard]) -> dict:
        status = candidate.high_stakes or self.classify(candidate)
        if status.get("risk_tier") != "high":
            return status
        domains = list(status.get("domains", []))
        authoritative_tokens = [token for domain in domains for token in self.AUTHORITATIVE_HINTS.get(domain, [])]
        approved = [card for card in cards if card.approved]
        source_blob = _lower_blob(
            [{"publisher": card.publisher, "source_type": card.source_type, "title": card.title} for card in approved]
        )
        authoritative = bool(approved) and any(token in source_blob for token in authoritative_tokens)
        current = bool(approved) and all(card.timeliness_score >= 0.70 for card in approved)
        blockers = []
        if not authoritative:
            blockers.append("High-stakes claim requires authoritative source evidence")
        if not current:
            blockers.append("High-stakes claim requires current evidence")
        updated = {
            **status,
            "authoritative_evidence_met": authoritative,
            "currentness_met": current,
            "decision": "PASS" if not blockers else "HOLD_FOR_OPERATOR",
            "blockers": blockers,
        }
        return updated

    def gate(self, candidate: CandidatePost) -> dict:
        status = candidate.high_stakes or self.classify(candidate)
        blockers = list(status.get("blockers", []))
        if status.get("risk_tier") == "high":
            if not status.get("authoritative_evidence_met"):
                blockers.append("High-stakes claim requires authoritative source evidence")
            if not status.get("currentness_met"):
                blockers.append("High-stakes claim requires current evidence")
        return {"status": "PASS" if not blockers else "HOLD_FOR_OPERATOR", "blockers": sorted(set(blockers))}


class AbstentionAndRedundancyGuard:
    def precheck(self, candidate: CandidatePost, claims: list[Claim] | None = None, submitted_hashes: set[str] | None = None) -> dict:
        reasons = []
        checkable = [claim for claim in (claims or []) if claim.status == "CHECKABLE"]
        if claims is not None and not checkable:
            reasons.append("no_checkable_claim")
        if claims and all(claim.opinion_sarcasm_flag or claim.status == "ABSTAIN" for claim in claims):
            reasons.append("opinion_or_satire")
        if candidate.duplicate_of:
            reasons.append("semantic_duplicate")
        if submitted_hashes and candidate.canonical_hash in submitted_hashes:
            reasons.append("already_sufficiently_noted")
        return {
            "decision": "BLOCK" if reasons else "PASS",
            "reasons": sorted(set(reasons)),
            "checks": [
                "no-note controls",
                "public replay",
                "existing-note lookup",
                "semantic claim clustering",
                "recent local draft/submission history",
            ],
        }


class EvidenceFreshnessAndLifecycleMonitor:
    def assess(self, candidate: CandidatePost, cards: list[EvidenceCard]) -> dict:
        approved = [card for card in cards if card.approved]
        time_sensitive = self._time_sensitive(candidate)
        missing_dates = [card.id for card in approved if not card.date]
        stale_cards = []
        now = datetime.now(UTC)
        for card in approved:
            parsed = _parse_date(card.date)
            if parsed and (now - parsed).days > 730:
                stale_cards.append(card.id)
        blockers = []
        if time_sensitive and not approved:
            blockers.append("Freshness not established for time-sensitive claim")
        if missing_dates:
            blockers.append("Approved evidence is missing source dates")
        if stale_cards:
            blockers.append("Approved evidence may be superseded or stale")
        return {
            "time_sensitive": time_sensitive,
            "freshness_status": "PASS" if not blockers else "HOLD_FOR_OPERATOR",
            "blockers": blockers,
            "approved_source_count": len(approved),
            "stale_card_ids": stale_cards,
            "source_date_missing_card_ids": missing_dates,
            "post_submission_monitoring": [
                "source availability",
                "source hash",
                "correction or retraction",
                "post availability",
                "note status",
                "outcome regression",
            ],
        }

    def post_submission_snapshot(self, submission_id: str, cards: list[EvidenceCard]) -> dict:
        return {
            "submission_id": submission_id,
            "created_at": now_iso(),
            "source_hashes": {card.source_id: sha256_text(f"{card.url}|{card.date}|{card.snippet}") for card in cards if card.approved},
            "monitoring_status": "scheduled",
        }

    def _time_sensitive(self, candidate: CandidatePost) -> bool:
        blob = _lower_blob(candidate.text, candidate.note_tweet, candidate.note_request_suggestions)
        return any(token in blob for token in ["now", "today", "currently", "latest", "this week", "routine", "routinely"])


class LinkableEvidenceReportService:
    def build(self, candidate: CandidatePost, draft: DraftNote, claims: list[Claim], cards: list[EvidenceCard]) -> dict:
        approved = [card for card in cards if card.approved]
        return {
            "id": stable_id("evidence-report", draft.id),
            "report_version": "evidence-report-v1",
            "candidate_id": candidate.id,
            "draft_id": draft.id,
            "exact_text_hash": draft.exact_text_hash,
            "operator_route": f"/candidates/{candidate.id}",
            "public_permalink_enabled": False,
            "public_redactions": ["internal thresholds", "private X payloads", "credentials", "operator identifiers"],
            "claims": [{"id": claim.id, "text": claim.text, "status": claim.status} for claim in claims],
            "sources": [
                {
                    "source_id": card.source_id,
                    "url": card.url,
                    "title": card.title,
                    "publisher": card.publisher,
                    "date": card.date,
                    "retrieved_at": card.retrieved_at,
                    "approved": card.approved,
                    "snippet_hash": sha256_text(card.snippet),
                }
                for card in approved
            ],
            "uncertainty": {
                "counterevidence_count": sum(1 for card in cards if card.contradiction_score > 0.35),
                "unsupported_sentence_count": len([sentence for sentence in draft.factual_sentences if not draft.support_map_json.get(sentence)]),
            },
        }


class CrossPerspectiveHelpfulnessService:
    def assess(
        self,
        candidate: CandidatePost,
        draft: DraftNote,
        internal_score: InternalScore | None,
        x_evaluation: XEvaluationResult | None,
    ) -> dict:
        blockers = []
        internal_helpful = internal_score.helpfulness_probability if internal_score else 0.0
        x_helpful = x_evaluation.helpfulness_score if x_evaluation else 0.0
        source_quality = internal_score.source_quality_score if internal_score else 0.0
        request_boost = min(0.12, sum(int(item.get("count", 0)) for item in candidate.note_request_suggestions) / 100)
        score = round((0.40 * internal_helpful) + (0.30 * x_helpful) + (0.20 * source_quality) + request_boost, 3)
        if not internal_score:
            blockers.append("Cross-perspective helpfulness requires internal critique")
        if not x_evaluation:
            blockers.append("Cross-perspective helpfulness requires exact X evaluate_note result")
        if score < 0.62:
            blockers.append("Cross-perspective helpfulness score below threshold")
        if internal_score and internal_score.stability_risk > 0.75:
            blockers.append("High CRNH false-positive stability risk")
        return {
            "status": "PASS" if not blockers else "BLOCK",
            "score": score,
            "blockers": blockers,
            "signals": {
                "internal_helpfulness_probability": internal_helpful,
                "x_helpfulness_score": x_helpful,
                "source_quality_score": source_quality,
                "note_request_boost": request_boost,
            },
        }


class WritingOpportunityRanker:
    def rank(
        self,
        candidate: CandidatePost,
        claims: list[Claim],
        cards: list[EvidenceCard],
        writing_limit: WritingLimitSnapshot,
        costs: CostSummary,
    ) -> dict:
        blockers = []
        checkable_count = sum(1 for claim in claims if claim.status == "CHECKABLE")
        approved = [card for card in cards if card.approved]
        note_requests = sum(int(item.get("count", 0)) for item in candidate.note_request_suggestions)
        source_quality = sum(card.reliability_score for card in approved) / len(approved) if approved else 0.0
        score = round(min(1.0, 0.25 + note_requests / 25 + len(approved) / 10 + source_quality / 4), 3)
        if not checkable_count:
            blockers.append("No checkable claim for writing opportunity")
        if not approved:
            blockers.append("No approved evidence for writing opportunity")
        if not costs.within_budget:
            blockers.extend(costs.blockers or ["Cost budget blocks writing opportunity"])
        if writing_limit.estimated_writing_limit < 1:
            blockers.append("Writing limit estimate is exhausted")
        decision = "ALLOW_NOW"
        if blockers:
            decision = "BLOCK"
        elif score < 0.45:
            decision = "DEFER_LOW_PRIORITY"
        return {
            "decision": decision,
            "priority_score": score,
            "blockers": blockers,
            "inputs": {
                "checkable_claim_count": checkable_count,
                "approved_evidence_count": len(approved),
                "note_request_count": note_requests,
                "estimated_writing_limit": writing_limit.estimated_writing_limit,
                "daily_cost_within_budget": costs.within_budget,
            },
        }


@dataclass
class DataRetentionAndAccessControlService:
    settings: Settings

    def classify_candidate(self, candidate: CandidatePost) -> dict:
        return {
            "policy_version": "retention-rbac-v1",
            "permitted_use": self.settings.community_notes_data_use_purpose,
            "sensitivity": "platform_content_minimized",
            "rbac": {
                "operator": ["read", "review", "approve", "export"],
                "service": ["read", "write_audit"],
                "public": ["redacted_methodology_only"],
            },
            "ttl_days": {
                "raw_x_payload": 30,
                "portable_context": 180,
                "source_snapshots_and_hashes": 365,
                "evidence_reports": 365,
                "operator_feedback": 730,
                "audit_logs": 1095,
                "credential_metadata": 90,
            },
            "storage_minimization": "prefer ids, hashes, metadata, and short excerpts over full private platform content",
            "deletion_and_rehydration": "purge stale or unavailable content unless legal/incident hold applies",
        }


class MethodologyTransparencyRegistry:
    def card(self, public: bool = True) -> dict:
        card = {
            "methodology_version": "community-notes14-governance-v1",
            "source_policy": "Prefer official, primary, institutional, and high-reliability sources; treat platform and source text as untrusted input.",
            "retrieval_rules": ["ingest suggested links", "plan official/primary searches", "audit directness, timeliness, contradiction, and coverage"],
            "gate_definitions": [
                "exact text evaluate_note",
                "support map completeness",
                "internal critique",
                "operator approval",
                "cost budget",
                "policy scope",
                "bot identity",
                "audience/context",
                "media dependency",
                "high-stakes routing",
                "freshness",
                "abstention/redundancy",
                "cross-perspective helpfulness",
                "writing opportunity",
                "emergency stop",
            ],
            "eval_windows": ["rolling 50-note admission", "fixture/adversarial eval run", "official scoring replay placeholder"],
            "known_limitations": ["fixture providers are deterministic", "live docs drift monitor records review state but does not fetch in request path"],
            "data_use_constraints": "Community Notes API data is used solely for Community Notes AI note writing.",
            "incident_change_log": [],
        }
        if public:
            card["redactions"] = ["numeric private thresholds where exploitable", "credentials", "private X payloads", "operator identifiers"]
        else:
            card["prompt_and_model_versions"] = {"claim_extraction": "strict-json-v1", "draft_generation": "strict-json-v1"}
        return card


class PolicyAndDocumentationDriftMonitor:
    def status(self) -> dict:
        return {
            "status": "operator_review_required_before_non_test_writes",
            "last_checked_at": None,
            "material_change_freezes_writes": True,
            "sources": [
                {"name": "X API Community Notes docs", "url": "https://docs.x.com/x-api/community-notes"},
                {"name": "X API pricing and usage", "url": "https://developer.x.com/en/support/x-api"},
                {"name": "X Developer policy", "url": "https://developer.x.com/en/developer-terms/policy"},
                {"name": "X terms", "url": "https://x.com/en/tos"},
            ],
            "review_queue": [],
        }


@dataclass
class EmergencyStopAndIncidentResponseController:
    settings: Settings

    def state(self) -> dict:
        return {
            "external_writes_blocked": self.settings.emergency_stop_external_writes,
            "reason": self.settings.emergency_stop_reason,
            "blocks_all_external_writes": True,
            "response_actions": [
                "pause high-risk queues",
                "drain in-flight writes",
                "rollback prompt/gate/adapter/source-policy versions",
                "rotate credentials",
                "require re-enable approval audit",
            ],
        }

    def blockers(self) -> list[str]:
        if self.settings.emergency_stop_external_writes:
            reason = f": {self.settings.emergency_stop_reason}" if self.settings.emergency_stop_reason else ""
            return [f"Emergency stop blocks all external writes{reason}"]
        return []


class OperatorFeedbackAndEditDiffService:
    def record_decision(
        self,
        draft: DraftNote,
        action: str,
        previous_text: str | None = None,
        reason: str | None = None,
        gate_snapshot: dict | None = None,
    ) -> dict:
        before = previous_text if previous_text is not None else draft.text
        diff = list(difflib.unified_diff(before.splitlines(), draft.text.splitlines(), fromfile="before", tofile="after", lineterm=""))
        return {
            "action": action,
            "reason": reason or "",
            "exact_text_hash": draft.exact_text_hash,
            "edit_diff": diff,
            "gate_snapshot": gate_snapshot or {},
            "created_at": now_iso(),
            "learning_use": "evaluation_and_regression_only_no_foundation_training",
        }


class OfficialScoringReplayService:
    def status(self) -> dict:
        return {
            "status": "fixture_replay_available",
            "purpose": "Replay scoring outcomes against gate/prompt changes before production writes.",
            "inputs": ["notes_written", "test_result", "scoring_status", "CRH", "CRNH", "NMR", "ClaimOpinion", "UrlValidity", "HarassmentAbuse"],
            "blocks_non_test_on_regression": True,
        }


class FeedStrategyAndCadenceManager:
    def plan(self, writing_limit: WritingLimitSnapshot, costs: CostSummary, test_mode: bool, max_results: int) -> dict:
        eligibility = writing_limit.feed_size_eligibility
        feed_size = "small"
        for candidate_size in ["xxl", "xl", "large", "small"]:
            allowed = eligibility.get(candidate_size, {})
            if allowed.get("eligible") and (test_mode or not allowed.get("non_test_mode_only")):
                feed_size = candidate_size
                break
        cadence = "manual_or_low_cadence" if not costs.within_budget else "normal_review_cadence"
        return {
            "feed_lang": "en",
            "feed_size": feed_size,
            "cadence": cadence,
            "max_results": max(1, min(max_results, 100)),
            "test_mode": test_mode,
            "budget_within_limit": costs.within_budget,
        }
