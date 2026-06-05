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
    XEvaluationResult,
    new_id,
)
from app.services.admission import AdmissionDashboardService
from app.services.costs import CostLedger
from app.services.evals import EvalHarness
from app.services.gate import ProductionReadinessGuard, SubmissionGate
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
from app.x_client.community_notes import FixtureXCommunityNotesClient


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cost_ledger = CostLedger(settings)
        self.x_client = FixtureXCommunityNotesClient(settings, self.cost_ledger)
        self.normalizer = CandidateNormalizer()
        self.claim_extractor = ClaimExtractor()
        self.source_ingestor = SourceSuggestionIngestor()
        self.search_planner = SearchPlanner()
        self.evidence_retriever = EvidenceRetriever(settings)
        self.evidence_auditor = EvidenceAuditor()
        self.draft_generator = DraftGenerator()
        self.internal_critic = InternalCritic()
        self.admission_service = AdmissionDashboardService(settings)
        self.writing_limit_monitor = WritingLimitMonitor()
        self.eval_harness = EvalHarness()
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

    def audit(self, event_type: str, entity_type: str, entity_id: str, message: str, metadata: dict | None = None) -> None:
        self.audit_events.append(
            AuditEvent(id=new_id(), event_type=event_type, entity_type=entity_type, entity_id=entity_id, message=message, metadata=metadata or {})
        )

    def sync_eligible_posts(self, max_results: int = 20, test_mode: bool = True) -> list[CandidatePost]:
        response = self.x_client.search_posts_eligible_for_notes(test_mode=test_mode, max_results=max_results)
        known_hashes = {candidate.canonical_hash: candidate.id for candidate in self.candidates.values()}
        synced = []
        for raw in response["posts"]:
            candidate = self.normalizer.from_x_post(raw)
            if candidate.canonical_hash in known_hashes:
                existing = self.candidates[known_hashes[candidate.canonical_hash]]
                synced.append(existing)
                continue
            self.candidates[candidate.id] = candidate
            self.raw_fixtures_by_candidate[candidate.id] = raw
            known_hashes[candidate.canonical_hash] = candidate.id
            synced.append(candidate)
            self.audit("sync", "candidate", candidate.id, "Synced eligible post fixture", {"x_post_id": candidate.x_post_id})
        return synced

    def seed_history(self) -> list[NotesWrittenSnapshot]:
        self.notes_written = [NotesWrittenSnapshot(**row) for row in fixture_notes_written()]
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
        candidate.status = "NO_NOTE" if claims and all(claim.status == "ABSTAIN" for claim in claims) else "ANALYZED"
        self.audit("analyze", "candidate", candidate_id, "Extracted checkable claims", {"claim_count": len(claims), "status": candidate.status})
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
        candidate.status = "RETRIEVED" if any(card.approved for card in cards) else candidate.status
        self.audit("retrieve", "candidate", candidate_id, "Retrieved and audited evidence", {"approved_cards": sum(1 for card in cards if card.approved)})
        return cards

    def generate_drafts(self, candidate_id: str) -> list[DraftNote]:
        candidate = self.candidates[candidate_id]
        raw = self.raw_fixtures_by_candidate[candidate_id]
        claims = self.claims.get(candidate_id) or self.analyze_candidate(candidate_id)
        cards = self.evidence_cards.get(candidate_id) or self.retrieve_evidence(candidate_id)
        drafts = self.draft_generator.generate(candidate, raw, claims, cards)
        self.drafts_by_candidate[candidate_id] = []
        for draft in drafts:
            self.drafts[draft.id] = draft
            self.drafts_by_candidate[candidate_id].append(draft.id)
        candidate.status = "DRAFTED" if any(draft.status == "DRAFTED" for draft in drafts) else candidate.status
        self.audit("draft", "candidate", candidate_id, "Generated draft candidates", {"draft_count": len(drafts)})
        return drafts

    def critique_draft(self, draft_id: str) -> InternalScore:
        draft = self.drafts[draft_id]
        cards = self.evidence_cards.get(draft.candidate_id, [])
        score = self.internal_critic.critique(draft, cards)
        self.internal_scores[draft_id] = score
        self.audit("critique", "draft", draft_id, "Ran internal critique", {"grounding_pass": score.grounding_pass})
        return score

    def evaluate_x(self, draft_id: str) -> XEvaluationResult:
        draft = self.drafts[draft_id]
        candidate = self.candidates[draft.candidate_id]
        result = self.x_client.evaluate_note(candidate.x_post_id, draft.text)
        result.draft_id = draft.id
        result.candidate_id = candidate.id
        self.x_evaluations[draft.id] = result
        self.audit("evaluate_x", "draft", draft_id, "Ran fixture X evaluate_note", {"claim_opinion_score": result.claim_opinion_score})
        return result

    def approve_draft(self, draft_id: str, override_reason: str | None = None) -> DraftNote:
        draft = self.drafts[draft_id]
        draft.operator_approved = True
        draft.operator_override_reason = override_reason
        draft.status = "REVIEWED"
        self.audit("approve", "draft", draft_id, "Operator approved exact draft text", {"exact_text_hash": draft.exact_text_hash})
        return draft

    def gate_for_draft(self, draft_id: str, test_mode: bool = True):
        draft = self.drafts[draft_id]
        candidate = self.candidates[draft.candidate_id]
        admission = self.admission()
        readiness = ProductionReadinessGuard(self.settings, admission.eligible_boolean)
        gate = SubmissionGate(self.settings, self.cost_ledger, readiness)
        return gate.evaluate(candidate, draft, self.internal_scores.get(draft_id), self.x_evaluations.get(draft_id), test_mode)

    def refresh_usage_reconciliation(self) -> dict:
        usage = self.x_client.get_usage()
        self.cost_ledger.reconcile_usage_api(usage.get("usage_api", {}))
        return self.cost_ledger.to_dict()

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
        )
        self.submissions[submission.id] = submission
        candidate.status = "SUBMITTED_TEST" if test_mode else "SUBMITTED_LIVE"
        self.audit("submit", "draft", draft_id, "Submitted fixture note", {"test_mode": test_mode, "submission_id": submission.id})
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
        return self.notes_written

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
            "policy_scope": self.settings.policy_scope(),
            "bot_identity": self.settings.bot_identity(),
            "regression_alerts": admission.blockers + costs.blockers,
        }
