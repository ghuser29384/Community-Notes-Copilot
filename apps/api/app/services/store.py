from __future__ import annotations

from app.fixtures import fixture_eligible_posts, fixture_notes_written
from app.models.records import (
    AuditEvent,
    CandidatePost,
    Claim,
    DraftNote,
    EvidenceCard,
    EvidenceSource,
    InternalScore,
    NotesWrittenSnapshot,
    Submission,
    CostLedgerEntry,
    XEvaluationResult,
    new_id,
)
from app.services.admission import AdmissionDashboardService
from app.services.costs import CostLedger
from app.services.evals import EvalHarness
from app.services.gate import ProductionReadinessGuard, SubmissionGate
from app.services.governance import (
    AbstentionAndRedundancyGuard,
    AudienceContextService,
    CrossPerspectiveHelpfulnessService,
    DataRetentionAndAccessControlService,
    EmergencyStopAndIncidentResponseController,
    EvidenceFreshnessAndLifecycleMonitor,
    FeedStrategyAndCadenceManager,
    HighStakesDomainRouter,
    LatencySLOAndGracefulDegradationService,
    LinkableEvidenceReportService,
    MediaDependencyGate,
    MethodologyTransparencyRegistry,
    OfficialScoringReplayService,
    PhasedDeliveryAndComplexityBudget,
    PlatformAdapter,
    PolicyAndDocumentationDriftMonitor,
    OperatorFeedbackAndEditDiffService,
    WritingOpportunityRanker,
)
from app.services.normalizer import CandidateNormalizer
from app.services.pipeline import (
    ClaimExtractor,
    DraftGenerator,
    EvidenceAuditor,
    EvidenceRetriever,
    InternalCritic,
    SearchPlanner,
    SourceSuggestionIngestor,
)
from app.services.writing_limit import WritingLimitMonitor
from app.settings import Settings
from app.storage import build_record_store
from app.x_client.community_notes import FixtureXCommunityNotesClient, LiveXCommunityNotesClient


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cost_ledger = CostLedger(settings)
        self.cost_ledger.on_entry = self._persist_cost_entry
        self.cost_ledger.on_state_change = self._persist_cost_state
        self.x_client = LiveXCommunityNotesClient(settings, self.cost_ledger) if settings.x_provider == "live" else FixtureXCommunityNotesClient(settings, self.cost_ledger)
        self.normalizer = CandidateNormalizer()
        self.claim_extractor = ClaimExtractor(settings)
        self.source_ingestor = SourceSuggestionIngestor()
        self.search_planner = SearchPlanner()
        self.evidence_retriever = EvidenceRetriever(settings)
        self.evidence_auditor = EvidenceAuditor()
        self.draft_generator = DraftGenerator(settings)
        self.internal_critic = InternalCritic()
        self.admission_service = AdmissionDashboardService(settings)
        self.writing_limit_monitor = WritingLimitMonitor()
        self.eval_harness = EvalHarness()
        self.phase_budget = PhasedDeliveryAndComplexityBudget(settings)
        self.latency_slo = LatencySLOAndGracefulDegradationService(settings)
        self.platform_adapter = PlatformAdapter(settings)
        self.audience_context = AudienceContextService()
        self.media_gate = MediaDependencyGate(settings)
        self.high_stakes_router = HighStakesDomainRouter()
        self.abstention_guard = AbstentionAndRedundancyGuard()
        self.freshness_monitor = EvidenceFreshnessAndLifecycleMonitor()
        self.evidence_reporter = LinkableEvidenceReportService()
        self.cross_perspective = CrossPerspectiveHelpfulnessService()
        self.writing_ranker = WritingOpportunityRanker()
        self.retention = DataRetentionAndAccessControlService(settings)
        self.methodology = MethodologyTransparencyRegistry()
        self.policy_drift = PolicyAndDocumentationDriftMonitor()
        self.emergency_stop = EmergencyStopAndIncidentResponseController(settings)
        self.operator_feedback = OperatorFeedbackAndEditDiffService()
        self.official_scoring_replay = OfficialScoringReplayService()
        self.feed_strategy = FeedStrategyAndCadenceManager()
        self.candidates: dict[str, CandidatePost] = {}
        self.raw_fixtures_by_candidate: dict[str, dict] = {}
        self.claims: dict[str, list[Claim]] = {}
        self.sources: dict[str, list[EvidenceSource]] = {}
        self.evidence_cards: dict[str, list[EvidenceCard]] = {}
        self.drafts: dict[str, DraftNote] = {}
        self.drafts_by_candidate: dict[str, list[str]] = {}
        self.internal_scores: dict[str, InternalScore] = {}
        self.x_evaluations: dict[str, XEvaluationResult] = {}
        self.submissions: dict[str, Submission] = {}
        self.notes_written: list[NotesWrittenSnapshot] = []
        self.audit_events: list[AuditEvent] = []
        self.record_store = build_record_store(settings)
        self._load_persisted_state()

    def audit(self, event_type: str, entity_type: str, entity_id: str, message: str, metadata: dict | None = None) -> None:
        event = AuditEvent(id=new_id(), event_type=event_type, entity_type=entity_type, entity_id=entity_id, message=message, metadata=metadata or {})
        self.audit_events.append(event)
        self._persist_dataclass("audit_event", event, parent_id=entity_id)

    def _persist_dataclass(self, record_type: str, record, parent_id: str | None = None, canonical_hash: str | None = None) -> None:
        self.record_store.upsert(record_type, record.id, record.to_dict(), parent_id=parent_id, canonical_hash=canonical_hash)

    def _persist_raw_candidate(self, candidate_id: str, raw: dict) -> None:
        self.record_store.upsert("raw_candidate", candidate_id, {"id": candidate_id, "candidate_id": candidate_id, "raw": raw}, parent_id=candidate_id)

    def _persist_cost_entry(self, entry) -> None:
        self._persist_dataclass("cost_entry", entry, parent_id=entry.entity_id)

    def _persist_cost_state(self) -> None:
        self.record_store.upsert(
            "cost_state",
            "default",
            {
                "id": "default",
                "usage_api_snapshot": self.cost_ledger.usage_api_snapshot,
                "developer_console_checked_at": self.cost_ledger.developer_console_checked_at,
            },
        )

    def _load_persisted_state(self) -> None:
        if not self.record_store.enabled:
            return
        self.candidates = {item["id"]: CandidatePost.validate_dict(item) for item in self.record_store.list_records("candidate")}
        self.raw_fixtures_by_candidate = {
            item["candidate_id"]: item.get("raw", {}) for item in self.record_store.list_records("raw_candidate")
        }
        self.claims = {}
        for item in self.record_store.list_records("claim"):
            claim = Claim.validate_dict(item)
            self.claims.setdefault(claim.candidate_id, []).append(claim)
        self.sources = {}
        for item in self.record_store.list_records("source"):
            source = EvidenceSource.validate_dict(item)
            self.sources.setdefault(source.candidate_id, []).append(source)
        self.evidence_cards = {}
        for item in self.record_store.list_records("evidence_card"):
            card = EvidenceCard.validate_dict(item)
            self.evidence_cards.setdefault(card.candidate_id, []).append(card)
        self.drafts = {}
        self.drafts_by_candidate = {}
        for item in self.record_store.list_records("draft"):
            draft = DraftNote.validate_dict(item)
            self.drafts[draft.id] = draft
            self.drafts_by_candidate.setdefault(draft.candidate_id, []).append(draft.id)
        self.internal_scores = {}
        for item in self.record_store.list_records("internal_score"):
            score = InternalScore.validate_dict(item)
            self.internal_scores[score.draft_id] = score
        self.x_evaluations = {}
        for item in self.record_store.list_records("x_evaluation"):
            result = XEvaluationResult.validate_dict(item)
            self.x_evaluations[result.draft_id] = result
        self.submissions = {item["id"]: Submission.validate_dict(item) for item in self.record_store.list_records("submission")}
        self.notes_written = [NotesWrittenSnapshot.validate_dict(item) for item in self.record_store.list_records("notes_written")]
        self.audit_events = [AuditEvent.validate_dict(item) for item in self.record_store.list_records("audit_event")]
        self.cost_ledger.entries = []
        for item in self.record_store.list_records("cost_entry"):
            self.cost_ledger.entries.append(CostLedgerEntry.validate_dict(item))
        cost_state = self.record_store.get("cost_state", "default")
        if cost_state:
            self.cost_ledger.usage_api_snapshot = cost_state.get("usage_api_snapshot")
            self.cost_ledger.developer_console_checked_at = cost_state.get("developer_console_checked_at")
        for item in self.record_store.list_records("eval_run"):
            self.eval_harness.runs[item["id"]] = item

    def sync_eligible_posts(self, max_results: int = 20, test_mode: bool = True) -> list[CandidatePost]:
        feed_plan = self.feed_strategy.plan(self.writing_limit(), self.cost_ledger.summary(), test_mode, max_results)
        response = self.x_client.search_posts_eligible_for_notes(
            test_mode=test_mode,
            max_results=feed_plan["max_results"],
            feed_lang=feed_plan["feed_lang"],
            feed_size=feed_plan["feed_size"],
        )
        known_hashes = {candidate.canonical_hash: candidate.id for candidate in self.candidates.values()}
        synced = []
        for raw in response["posts"]:
            candidate = self.normalizer.from_x_post(raw)
            self._initialize_candidate_governance(candidate, raw, feed_plan)
            if candidate.canonical_hash in known_hashes:
                existing = self.candidates[known_hashes[candidate.canonical_hash]]
                synced.append(existing)
                continue
            self.candidates[candidate.id] = candidate
            self.raw_fixtures_by_candidate[candidate.id] = raw
            self._persist_dataclass("candidate", candidate, canonical_hash=candidate.canonical_hash)
            self._persist_raw_candidate(candidate.id, raw)
            known_hashes[candidate.canonical_hash] = candidate.id
            synced.append(candidate)
            self.audit(
                "sync",
                "candidate",
                candidate.id,
                "Synced eligible post",
                {"x_post_id": candidate.x_post_id, "feed_strategy": feed_plan, "latency_slo": self.latency_slo.stage_budget("sync")},
            )
        return synced

    def _initialize_candidate_governance(self, candidate: CandidatePost, raw: dict, feed_plan: dict | None = None) -> None:
        candidate.platform_context = self.platform_adapter.from_x_payload(candidate, raw)
        candidate.audience_context = self.audience_context.classify(candidate)
        candidate.media_dependency = self.media_gate.classify(candidate)
        candidate.high_stakes = self.high_stakes_router.classify(candidate)
        candidate.abstention_guard = self.abstention_guard.precheck(candidate)
        candidate.freshness_lifecycle = {
            "freshness_status": "PENDING_EVIDENCE",
            "blockers": [],
            "post_submission_monitoring": [
                "source availability",
                "source hash",
                "correction or retraction",
                "post availability",
                "note status",
                "outcome regression",
            ],
        }
        candidate.retention_policy = self.retention.classify_candidate(candidate)
        candidate.feed_strategy = feed_plan or {}

    def _submitted_candidate_hashes(self) -> set[str]:
        submitted_candidate_ids = {submission.candidate_id for submission in self.submissions.values()}
        return {candidate.canonical_hash for candidate in self.candidates.values() if candidate.id in submitted_candidate_ids}

    def _candidate_governance_blockers(self, candidate: CandidatePost) -> list[str]:
        blockers: list[str] = []
        blockers.extend(candidate.abstention_guard.get("reasons", []))
        blockers.extend(candidate.media_dependency.get("blockers", []))
        blockers.extend(self.high_stakes_router.gate(candidate).get("blockers", []))
        blockers.extend(self.audience_context.gate(candidate).get("blockers", []))
        blockers.extend(candidate.freshness_lifecycle.get("blockers", []))
        return sorted(set(blockers))

    def _update_draft_governance(self, draft_id: str) -> DraftNote:
        draft = self.drafts[draft_id]
        candidate = self.candidates[draft.candidate_id]
        claims = self.claims.get(candidate.id, [])
        cards = self.evidence_cards.get(candidate.id, [])
        if not draft.evidence_report:
            draft.evidence_report = self.evidence_reporter.build(candidate, draft, claims, cards)
        draft.methodology = self.methodology.card(public=False)
        draft.writing_opportunity = self.writing_ranker.rank(candidate, claims, cards, self.writing_limit(), self.cost_ledger.summary())
        draft.cross_perspective = self.cross_perspective.assess(
            candidate,
            draft,
            self.internal_scores.get(draft_id),
            self.x_evaluations.get(draft_id),
        )
        self._persist_dataclass("draft", draft, parent_id=draft.candidate_id)
        return draft

    def seed_history(self) -> list[NotesWrittenSnapshot]:
        if self.notes_written:
            return self.notes_written
        self.notes_written = [NotesWrittenSnapshot(**row) for row in fixture_notes_written()]
        for note in self.notes_written:
            self._persist_dataclass("notes_written", note, parent_id=note.candidate_id)
        return self.notes_written

    def list_candidates(self) -> list[dict]:
        return [self.candidate_detail(candidate_id, compact=True) for candidate_id in self.candidates]

    def candidate_detail(self, candidate_id: str, compact: bool = False) -> dict:
        candidate = self.candidates[candidate_id]
        data = candidate.to_dict()
        data["claims"] = [claim.to_dict() for claim in self.claims.get(candidate_id, [])]
        data["sources"] = [source.to_dict() for source in self.sources.get(candidate_id, [])]
        data["evidence_cards"] = [card.to_dict() for card in self.evidence_cards.get(candidate_id, [])]
        data["drafts"] = [self.drafts[draft_id].to_dict() for draft_id in self.drafts_by_candidate.get(candidate_id, [])]
        if not compact:
            data["audit_events"] = [event.to_dict() for event in self.audit_events if event.entity_id in {candidate_id, candidate.x_post_id}]
        return data

    def analyze_candidate(self, candidate_id: str) -> list[Claim]:
        candidate = self.candidates[candidate_id]
        raw = self.raw_fixtures_by_candidate[candidate_id]
        claims = self.claim_extractor.extract(candidate, raw)
        self.claims[candidate_id] = claims
        candidate.abstention_guard = self.abstention_guard.precheck(candidate, claims, self._submitted_candidate_hashes())
        if candidate.media_dependency.get("decision") == "HOLD_FOR_OPERATOR":
            candidate.status = "HELD_FOR_OPERATOR"
        elif candidate.abstention_guard.get("decision") == "BLOCK":
            candidate.status = "NO_NOTE"
        else:
            candidate.status = "ANALYZED"
        self.record_store.delete_by_parent("claim", candidate_id)
        self._persist_dataclass("candidate", candidate, canonical_hash=candidate.canonical_hash)
        for claim in claims:
            self._persist_dataclass("claim", claim, parent_id=candidate_id)
        self.audit(
            "analyze",
            "candidate",
            candidate_id,
            "Extracted checkable claims and ran abstention/media prechecks",
            {
                "claim_count": len(claims),
                "status": candidate.status,
                "abstention_guard": candidate.abstention_guard,
                "media_dependency": candidate.media_dependency,
                "latency_slo": self.latency_slo.stage_budget("analyze"),
            },
        )
        return claims

    def retrieve_evidence(self, candidate_id: str) -> list[EvidenceCard]:
        candidate = self.candidates[candidate_id]
        raw = self.raw_fixtures_by_candidate[candidate_id]
        claims = self.claims.get(candidate_id) or self.analyze_candidate(candidate_id)
        sources = self.source_ingestor.ingest(candidate)
        self.sources[candidate_id] = sources
        self.search_planner.plan(claims)
        cards = self.evidence_retriever.retrieve(candidate, claims, raw, sources)
        cards = self.evidence_auditor.audit(cards)
        self.evidence_cards[candidate_id] = cards
        candidate.high_stakes = self.high_stakes_router.evaluate_evidence(candidate, cards)
        candidate.freshness_lifecycle = self.freshness_monitor.assess(candidate, cards)
        governance_blockers = self._candidate_governance_blockers(candidate)
        if governance_blockers:
            candidate.status = "HELD_FOR_OPERATOR" if candidate.status != "NO_NOTE" else candidate.status
        elif any(card.approved for card in cards):
            candidate.status = "RETRIEVED"
        self.record_store.delete_by_parent("source", candidate_id)
        self.record_store.delete_by_parent("evidence_card", candidate_id)
        self._persist_dataclass("candidate", candidate, canonical_hash=candidate.canonical_hash)
        for source in sources:
            self._persist_dataclass("source", source, parent_id=candidate_id)
        for card in cards:
            self._persist_dataclass("evidence_card", card, parent_id=candidate_id)
        self.audit(
            "retrieve",
            "candidate",
            candidate_id,
            "Retrieved evidence and ran high-stakes/freshness lifecycle checks",
            {
                "approved_cards": sum(1 for card in cards if card.approved),
                "high_stakes": candidate.high_stakes,
                "freshness_lifecycle": candidate.freshness_lifecycle,
                "latency_slo": self.latency_slo.stage_budget("retrieve"),
            },
        )
        return cards

    def generate_drafts(self, candidate_id: str) -> list[DraftNote]:
        candidate = self.candidates[candidate_id]
        raw = self.raw_fixtures_by_candidate[candidate_id]
        claims = self.claims.get(candidate_id) or self.analyze_candidate(candidate_id)
        cards = self.evidence_cards.get(candidate_id) or self.retrieve_evidence(candidate_id)
        governance_blockers = self._candidate_governance_blockers(candidate)
        if governance_blockers:
            drafts = [
                DraftNote(
                    id=new_id(),
                    candidate_id=candidate.id,
                    text="HOLD: CommunityNotes14 governance checks require operator review or abstention before drafting/submission.",
                    status="HOLD_FOR_OPERATOR",
                    factual_sentences=[],
                    support_map_json={},
                    evidence_brief="\n".join(governance_blockers),
                )
            ]
        else:
            drafts = self.draft_generator.generate(candidate, raw, claims, cards)
        self.record_store.delete_by_parent("draft", candidate_id)
        self.drafts_by_candidate[candidate_id] = []
        for draft in drafts:
            draft.evidence_report = self.evidence_reporter.build(candidate, draft, claims, cards)
            draft.methodology = self.methodology.card(public=False)
            draft.writing_opportunity = self.writing_ranker.rank(candidate, claims, cards, self.writing_limit(), self.cost_ledger.summary())
            draft.cross_perspective = self.cross_perspective.assess(
                candidate,
                draft,
                self.internal_scores.get(draft.id),
                self.x_evaluations.get(draft.id),
            )
            self.drafts[draft.id] = draft
            self.drafts_by_candidate[candidate_id].append(draft.id)
            self._persist_dataclass("draft", draft, parent_id=candidate_id)
        candidate.status = "DRAFTED" if any(draft.status == "DRAFTED" for draft in drafts) else candidate.status
        self._persist_dataclass("candidate", candidate, canonical_hash=candidate.canonical_hash)
        self.audit(
            "draft",
            "candidate",
            candidate_id,
            "Generated draft candidates with evidence reports and writing-opportunity ranking",
            {"draft_count": len(drafts), "governance_blockers": governance_blockers, "latency_slo": self.latency_slo.stage_budget("draft")},
        )
        return drafts

    def critique_draft(self, draft_id: str) -> InternalScore:
        draft = self.drafts[draft_id]
        cards = self.evidence_cards.get(draft.candidate_id, [])
        score = self.internal_critic.critique(draft, cards)
        self.internal_scores[draft_id] = score
        self._persist_dataclass("internal_score", score, parent_id=draft_id)
        self._update_draft_governance(draft_id)
        self.audit(
            "critique",
            "draft",
            draft_id,
            "Ran internal critique and refreshed cross-perspective helpfulness",
            {"grounding_pass": score.grounding_pass, "latency_slo": self.latency_slo.stage_budget("critique")},
        )
        return score

    def evaluate_x(self, draft_id: str) -> XEvaluationResult:
        draft = self.drafts[draft_id]
        candidate = self.candidates[draft.candidate_id]
        result = self.x_client.evaluate_note(candidate.x_post_id, draft.text)
        result.draft_id = draft.id
        result.candidate_id = candidate.id
        self.x_evaluations[draft.id] = result
        self._persist_dataclass("x_evaluation", result, parent_id=draft.id)
        self._update_draft_governance(draft_id)
        self.audit(
            "evaluate_x",
            "draft",
            draft_id,
            "Ran X evaluate_note and refreshed cross-perspective helpfulness",
            {"claim_opinion_score": result.claim_opinion_score, "latency_slo": self.latency_slo.stage_budget("evaluate_x")},
        )
        return result

    def approve_draft(self, draft_id: str, override_reason: str | None = None) -> DraftNote:
        draft = self.drafts[draft_id]
        previous_text = draft.text
        draft.operator_approved = True
        draft.operator_override_reason = override_reason
        draft.status = "REVIEWED"
        draft.operator_feedback.append(
            self.operator_feedback.record_decision(
                draft,
                "approve_with_override" if override_reason else "approve",
                previous_text=previous_text,
                reason=override_reason,
            )
        )
        self._persist_dataclass("draft", draft, parent_id=draft.candidate_id)
        self.audit(
            "approve",
            "draft",
            draft_id,
            "Operator approved exact draft text and recorded edit-diff feedback",
            {"exact_text_hash": draft.exact_text_hash, "operator_feedback": draft.operator_feedback[-1]},
        )
        return draft

    def gate_for_draft(self, draft_id: str, test_mode: bool = True):
        self._update_draft_governance(draft_id)
        draft = self.drafts[draft_id]
        candidate = self.candidates[draft.candidate_id]
        admission = self.admission()
        readiness = ProductionReadinessGuard(self.settings, admission.eligible_boolean)
        gate = SubmissionGate(self.settings, self.cost_ledger, readiness, extra_blockers=self.emergency_stop.blockers())
        return gate.evaluate(candidate, draft, self.internal_scores.get(draft_id), self.x_evaluations.get(draft_id), test_mode)

    def refresh_usage_reconciliation(self) -> dict:
        try:
            usage = self.x_client.get_usage()
        except PermissionError as exc:
            data = self.cost_ledger.to_dict()
            data["usage_reconciliation_error"] = str(exc)
            return data
        self.cost_ledger.reconcile_usage_api(usage.get("usage_api", {}))
        return self.cost_ledger.to_dict()

    def provider_readiness(self) -> dict:
        blockers = []
        if self.settings.x_provider == "live":
            if not self.settings.allow_live_x_api:
                blockers.append("Live X provider selected but ALLOW_LIVE_X_API=false")
            if not self.settings.x_bearer_token:
                blockers.append("X_BEARER_TOKEN is required for live X API calls")
        if self.settings.search_provider == "brave" and not self.settings.allow_live_search:
            blockers.append("Brave search provider selected but ALLOW_LIVE_SEARCH=false")
        if self.settings.llm_provider == "openai" and not self.settings.allow_live_llm:
            blockers.append("OpenAI LLM provider selected but ALLOW_LIVE_LLM=false")
        return {
            "x_live_read_ready": self.settings.x_provider != "live" or (self.settings.allow_live_x_api and bool(self.settings.x_bearer_token)),
            "search_live_ready": self.settings.search_provider != "brave" or self.settings.allow_live_search,
            "llm_live_ready": self.settings.llm_provider != "openai" or self.settings.allow_live_llm,
            "blockers": blockers,
        }

    def submit_draft(self, draft_id: str, test_mode: bool = True) -> tuple[Submission | None, object]:
        draft = self.drafts[draft_id]
        candidate = self.candidates[draft.candidate_id]
        gate = self.gate_for_draft(draft_id, test_mode)
        if not gate.can_submit:
            return None, gate
        response = self.x_client.write_note(candidate.x_post_id, draft.text, test_mode=test_mode, info={"draft_id": draft.id})
        submission = Submission(
            id=new_id(),
            draft_id=draft.id,
            candidate_id=candidate.id,
            post_id=candidate.x_post_id,
            note_text=draft.text,
            exact_text_hash=draft.exact_text_hash,
            test_mode=test_mode,
            status="SUBMITTED_TEST" if test_mode else "SUBMITTED_LIVE",
            x_response=response,
            gate_snapshot=gate.__dict__,
        )
        submission.lifecycle_snapshot = self.freshness_monitor.post_submission_snapshot(submission.id, self.evidence_cards.get(candidate.id, []))
        self.submissions[submission.id] = submission
        candidate.status = "SUBMITTED_TEST" if test_mode else "SUBMITTED_LIVE"
        self._persist_dataclass("submission", submission, parent_id=draft.candidate_id)
        self._persist_dataclass("candidate", candidate, canonical_hash=candidate.canonical_hash)
        self.audit(
            "submit",
            "draft",
            draft_id,
            "Submitted note and scheduled evidence lifecycle monitoring",
            {"test_mode": test_mode, "submission_id": submission.id, "latency_slo": self.latency_slo.stage_budget("submit")},
        )
        return submission, gate

    def export_draft(self, draft_id: str, consent_ack: bool = False, consent_actor: str = "", consent_reason: str = "") -> str:
        if self.settings.track_a_requires_express_consent and not consent_ack:
            raise PermissionError("Track A export requires express and informed contributor consent; authentication alone is not enough")
        draft = self.drafts[draft_id]
        candidate = self.candidates[draft.candidate_id]
        self.audit(
            "track_a_consent",
            "draft",
            draft_id,
            "Recorded express Track A export consent",
            {"consent_actor": consent_actor, "consent_reason": consent_reason},
        )
        lines = [
            "Track A Community Notes export",
            f"Post ID: {candidate.x_post_id}",
            f"Exact text hash: {draft.exact_text_hash}",
            f"Express consent actor: {consent_actor or 'operator'}",
            f"Consent reason: {consent_reason or 'manual export/copy workflow'}",
            "",
            draft.text,
            "",
            "Support map:",
        ]
        for sentence, source_ids in draft.support_map_json.items():
            lines.append(f"- {sentence} -> {', '.join(source_ids)}")
        return "\n".join(lines)

    def sync_notes_written(self) -> list[NotesWrittenSnapshot]:
        response = self.x_client.notes_written(max_results=100)
        self.notes_written = [NotesWrittenSnapshot(**row) for row in response["notes"]]
        for note in self.notes_written:
            self._persist_dataclass("notes_written", note, parent_id=note.candidate_id)
        return self.notes_written

    def run_evals(self) -> dict:
        result = self.eval_harness.run()
        self.record_store.upsert("eval_run", result["id"], result)
        return result

    def get_eval_run(self, run_id: str) -> dict | None:
        return self.eval_harness.get(run_id) or self.record_store.get("eval_run", run_id)

    def admission(self):
        if not self.notes_written:
            self.seed_history()
        return self.admission_service.compute(self.notes_written)

    def writing_limit(self):
        if not self.notes_written:
            self.seed_history()
        return self.writing_limit_monitor.compute(self.notes_written)

    def dashboard(self) -> dict:
        admission = self.admission()
        writing = self.writing_limit()
        self.refresh_usage_reconciliation()
        costs = self.cost_ledger.summary()
        provider_readiness = self.provider_readiness()
        statuses = {}
        for candidate in self.candidates.values():
            statuses[candidate.status] = statuses.get(candidate.status, 0) + 1
        return {
            "queue_summary": {
                "total": len(self.candidates),
                "by_status": statuses,
                "submissions": len(self.submissions),
            },
            "admission": admission.to_dict(),
            "writing_limit": writing.to_dict(),
            "costs": costs.to_dict(),
            "provider_readiness": provider_readiness,
            "policy_scope": self.settings.policy_scope(),
            "bot_identity": self.settings.bot_identity(),
            "governance": self.governance_status(public=True),
            "regression_alerts": admission.blockers + costs.blockers + provider_readiness["blockers"],
        }

    def governance_status(self, public: bool = True) -> dict:
        return {
            "phase_and_complexity": self.phase_budget.status(),
            "latency_slo": self.latency_slo.status(),
            "methodology": self.methodology.card(public=public),
            "policy_drift": self.policy_drift.status(),
            "emergency_stop": self.emergency_stop.state(),
            "official_scoring_replay": self.official_scoring_replay.status(),
            "retention_and_access_control": {
                "policy_version": "retention-rbac-v1",
                "storage_minimization": "ids, hashes, metadata, and short excerpts preferred over full private platform content",
                "public_access": "redacted methodology only",
            },
        }
