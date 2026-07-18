from __future__ import annotations

from app.models.records import AdmissionWindow, NotesWrittenSnapshot, new_id
from app.settings import Settings


class AdmissionDashboardService:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _most_recent(notes: list[NotesWrittenSnapshot]) -> list[NotesWrittenSnapshot]:
        # The API normally returns newest first. Preserve that order when timestamps
        # are absent, but sort explicitly when timestamped fixtures or persisted data
        # make the ordering verifiable.
        if not any(note.created_at for note in notes):
            return list(notes)
        return sorted(notes, key=lambda note: note.created_at or "", reverse=True)

    def compute(self, notes: list[NotesWrittenSnapshot], window_size: int = 50) -> AdmissionWindow:
        ordered = self._most_recent(notes)
        window = ordered[:window_size]
        observed = len(window)
        denominator = observed or 1
        claim_high = sum(1 for note in window if note.claim_opinion == "high") / denominator
        claim_low = sum(1 for note in window if note.claim_opinion == "low") / denominator
        url_high = sum(1 for note in window if note.url_validity == "high") / denominator
        harassment_high = sum(1 for note in window if note.harassment_abuse == "high") / denominator
        blockers = []
        if observed < window_size:
            blockers.append(f"Admission window incomplete: {observed}/{window_size} test-mode notes")
        if claim_high < self.settings.admission_claim_opinion_high_min:
            blockers.append("ClaimOpinion high rate below 30%")
        if claim_low > self.settings.admission_claim_opinion_low_max:
            blockers.append("ClaimOpinion low rate above 30%")
        if url_high < self.settings.admission_url_validity_high_min:
            blockers.append("UrlValidity high rate below 95%")
        if harassment_high < self.settings.admission_harassment_abuse_high_min:
            blockers.append("HarassmentAbuse high rate below 98%")
        return AdmissionWindow(
            id=new_id(),
            window_size=observed,
            claim_opinion_high_rate=claim_high,
            claim_opinion_low_rate=claim_low,
            url_validity_high_rate=url_high,
            harassment_abuse_high_rate=harassment_high,
            eligible_boolean=not blockers,
            blockers=blockers,
            raw_inputs={
                "total": observed,
                "required_window_size": window_size,
                "observed_window_size": observed,
                "window_note_ids": [note.note_id for note in window],
                "thresholds": {
                    "ClaimOpinion_high_rate_min": self.settings.admission_claim_opinion_high_min,
                    "ClaimOpinion_low_rate_max": self.settings.admission_claim_opinion_low_max,
                    "UrlValidity_high_rate_min": self.settings.admission_url_validity_high_min,
                    "HarassmentAbuse_high_rate_min": self.settings.admission_harassment_abuse_high_min,
                },
            },
        )
