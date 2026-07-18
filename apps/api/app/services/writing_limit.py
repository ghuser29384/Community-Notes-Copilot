from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import floor

from app.models.records import NotesWrittenSnapshot, WritingLimitSnapshot, new_id


def _parse_date(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _most_recent(notes: list[NotesWrittenSnapshot]) -> list[NotesWrittenSnapshot]:
    parsed = [_parse_date(note.created_at) for note in notes]
    if not any(parsed):
        return list(notes)
    indexed = list(enumerate(notes))
    return [
        note
        for _, note in sorted(
            indexed,
            key=lambda item: (
                (_parse_date(item[1].created_at) or datetime.min.replace(tzinfo=UTC)).timestamp(),
                -item[0],
            ),
            reverse=True,
        )
    ]


def _writing_impact(notes: list[NotesWrittenSnapshot]) -> int:
    return sum(1 for note in notes if note.crh) - sum(1 for note in notes if note.crnh)


def _hit_rate(notes: list[NotesWrittenSnapshot]) -> float:
    return _writing_impact(notes) / (len(notes) or 1)


def _internal_writing_limit(hr_l: float, hr_r: float) -> float:
    if hr_l < 0.05:
        return 300 * max(hr_r, hr_l)
    if hr_l < 0.10:
        return 15 + 700 * (hr_l - 0.05)
    if hr_l < 0.15:
        return 50 + 3000 * (hr_l - 0.10)
    if hr_l < 0.20:
        return 200 + 6000 * (hr_l - 0.15)
    return 500.0


class WritingLimitMonitor:
    """Reproduce the published AI Note Writer limit and feed eligibility rules.

    NotesWrittenSnapshot does not currently retain rating counts. For HR_14d,
    NMR notes are therefore excluded unless X has already assigned CRH/CRNH;
    this is the conservative subset of the documented qualifying-note rule.
    """

    def compute(self, notes: list[NotesWrittenSnapshot]) -> WritingLimitSnapshot:
        recent = _most_recent(notes)
        total = len(recent)
        rated = [note for note in recent if not note.nmr and (note.crh or note.crnh)]
        nh_5 = sum(1 for note in rated[:5] if note.crnh)
        nh_10 = sum(1 for note in rated[:10] if note.crnh)

        recent_20 = recent[:20]
        recent_100 = recent[:100]
        hr_r = _hit_rate(recent_20)
        hr_100 = _hit_rate(recent_100)

        dated = [(note, _parse_date(note.created_at)) for note in recent]
        dated = [(note, parsed) for note, parsed in dated if parsed is not None]
        now = datetime.now(UTC)
        last_14: list[NotesWrittenSnapshot] = []
        last_30: list[NotesWrittenSnapshot] = []
        last_90: list[NotesWrittenSnapshot] = []
        for note, parsed in dated:
            age = now - parsed
            if timedelta(0) <= age <= timedelta(days=14):
                last_14.append(note)
            if timedelta(0) <= age <= timedelta(days=30):
                last_30.append(note)
            if timedelta(0) <= age <= timedelta(days=90):
                last_90.append(note)

        qualifying_14d = [note for note in last_14 if note.crh or note.crnh]
        hr_14d = _hit_rate(qualifying_14d)
        hr_l = max(hr_100, hr_14d)
        dn_30 = len(last_30) / 30.0
        wl_l = _internal_writing_limit(hr_l, hr_r)

        if nh_10 >= 8:
            estimated = 2
        elif nh_5 >= 3:
            estimated = 5
        elif total < 20:
            estimated = 10
        else:
            estimated = max(5, floor(min(dn_30 * 5, wl_l)))

        crnh_rate_100 = sum(1 for note in recent_100 if note.crnh) / (len(recent_100) or 1)
        high_performing = total >= 100 and hr_l >= 0.05 and crnh_rate_100 <= 0.10
        impact_90d = _writing_impact(last_90)
        feed_size_eligibility = {
            "small": {
                "eligible": True,
                "non_test_mode_only": False,
                "requirements": "Default eligible-post feed; language selection is also available in test mode.",
            },
            "medium": {
                "eligible": False,
                "non_test_mode_only": True,
                "requirements": "Not listed as a current AI Note Writer feed size; retained as a blocked legacy key.",
            },
            "large": {
                "eligible": high_performing,
                "non_test_mode_only": True,
                "requirements": "At least 100 notes, HR_L >= 5%, and recent-100 CRNH rate <= 10%.",
            },
            "xl": {
                "eligible": high_performing,
                "non_test_mode_only": True,
                "requirements": "At least 100 notes, HR_L >= 5%, and recent-100 CRNH rate <= 10%.",
            },
            "xxl": {
                "eligible": impact_90d >= 100,
                "non_test_mode_only": True,
                "requirements": "Writing Impact of at least 100 over the past 90 days.",
            },
        }

        return WritingLimitSnapshot(
            id=new_id(),
            wl=estimated,
            nh_5=nh_5,
            nh_10=nh_10,
            hr_r=hr_r,
            hr_100=hr_100,
            hr_14d=hr_14d,
            hr_l=hr_l,
            dn_30=dn_30,
            t=total,
            total_notes=total,
            estimated_writing_limit=estimated,
            feed_size_eligibility=feed_size_eligibility,
            writing_impact_90d={
                "notes": len(last_90),
                "crh": sum(1 for note in last_90 if note.crh),
                "crnh": sum(1 for note in last_90 if note.crnh),
                "nmr": sum(1 for note in last_90 if note.nmr),
                "net": impact_90d,
            },
            formulas={
                "NH_5": "CRNH count among the most recent 5 non-NMR notes",
                "NH_10": "CRNH count among the most recent 10 non-NMR notes",
                "HR_R": "(CRH - CRNH) / TotalNotes among the most recent 20 notes",
                "HR_100": "(CRH - CRNH) / TotalNotes among the most recent 100 notes",
                "HR_14d": "(CRH - CRNH) / qualifying notes over the trailing 14 days",
                "HR_L": "max(HR_100, HR_14d)",
                "DN_30": "notes written over the trailing 30 days / 30",
                "WL_L": "published piecewise function of HR_L and HR_R",
                "WL": "2 if NH_10>=8; 5 if NH_5>=3; 10 if T<20; otherwise max(5, floor(min(DN_30*5, WL_L)))",
            },
            raw_inputs={
                "note_count": total,
                "non_nmr_rated_count": len(rated),
                "recent_20_count": len(recent_20),
                "recent_100_count": len(recent_100),
                "last_14_count": len(last_14),
                "qualifying_14d_count": len(qualifying_14d),
                "last_30_count": len(last_30),
                "last_90_count": len(last_90),
                "crnh_rate_recent_100": crnh_rate_100,
                "wl_l": wl_l,
                "rating_count_limitation": "Per-note rating counts are not retained; NMR notes are excluded from HR_14d.",
                "test_results": {
                    "passed": sum(1 for note in recent if note.test_result == "passed"),
                    "needs_review": sum(1 for note in recent if note.test_result == "needs_review"),
                },
                "scoring_status": {
                    "scored": sum(1 for note in recent if note.scoring_status == "scored"),
                    "pending": sum(1 for note in recent if note.scoring_status == "pending"),
                },
            },
        )
