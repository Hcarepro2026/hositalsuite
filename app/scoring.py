"""Pure business logic: scoring, ratings, SLA, recurring-issue detection.

No framework dependencies so it can be unit tested directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

# ----------------------------------------------------------- THE FIVE CRITERIA
# Exactly five primary evaluation criteria — do not add a sixth.
CRITERIA: Dict[int, dict] = {
    1: {
        "code": "staff",
        "title": "Staff & Service Delivery",
        "items": ["Staff presence", "Duty coverage", "Punctuality", "Staff conduct",
                  "Responsiveness", "Patient/visitor handling", "Service delivery"],
    },
    2: {
        "code": "cleanliness",
        "title": "Cleanliness & Infection Prevention",
        "items": ["General cleanliness", "Working areas", "Toilets", "Handwashing facilities",
                  "Waste disposal", "Bed/clinical-area hygiene", "Infection-prevention practices"],
    },
    3: {
        "code": "equipment",
        "title": "Equipment, Facilities & Supplies",
        "items": ["Availability of required equipment", "Functionality", "Furniture", "Electricity",
                  "Water", "Lighting", "Ventilation", "Essential supplies", "Faulty equipment/facilities"],
    },
    4: {
        "code": "records",
        "title": "Records, Compliance & Accountability",
        "items": ["Required registers", "Documentation", "Attendance records", "Departmental records",
                  "SOP compliance", "Handover procedures", "Previous corrective actions"],
    },
    5: {
        "code": "safety",
        "title": "Safety, Security & Overall Condition",
        "items": ["Patient safety", "Staff safety", "Security", "Fire safety",
                  "Emergency preparedness", "Physical hazards", "Infrastructure condition",
                  "Emergency access"],
    },
}

CRITERIA_COUNT = 5
MAX_SCORE = CRITERIA_COUNT * 5          # 25

SCORE_LABELS = {
    5: "Excellent — Fully compliant",
    4: "Good — Minor issues requiring attention",
    3: "Fair — Improvement required",
    2: "Poor — Significant deficiency",
    1: "Critical — Immediate intervention required",
}


def validate_scores(scores: Dict[int, int]) -> List[str]:
    """Return a list of validation errors (empty = OK)."""
    errors: List[str] = []
    for no in range(1, CRITERIA_COUNT + 1):
        v = scores.get(no)
        if v is None:
            errors.append(f"Criterion {no} ({CRITERIA[no]['title']}) has no score.")
        elif not (1 <= int(v) <= 5):
            errors.append(f"Criterion {no} score must be between 1 and 5.")
    return errors


def explanation_required(score: int) -> bool:
    """Business rule: score 1 or 2 MUST have an explanation."""
    return int(score) <= 2


def calc_total(scores: Dict[int, int]) -> int:
    return sum(int(scores[n]) for n in range(1, CRITERIA_COUNT + 1))


def calc_percent(total: int) -> float:
    return round(total / MAX_SCORE * 100.0, 1)


def rating_for(total: int) -> str:
    if total >= 22:
        return "EXCELLENT"
    if total >= 18:
        return "GOOD"
    if total >= 13:
        return "FAIR / NEEDS IMPROVEMENT"
    if total >= 8:
        return "POOR"
    return "CRITICAL"


RATING_COLORS = {
    "EXCELLENT": "#1a7f37",
    "GOOD": "#4d9e3f",
    "FAIR / NEEDS IMPROVEMENT": "#b58900",
    "POOR": "#d97706",
    "CRITICAL": "#c0262c",
}


def flagged_criteria(scores: Dict[int, int]) -> List[int]:
    return [n for n in range(1, CRITERIA_COUNT + 1) if int(scores[n]) <= 2]


def critical_count(scores: Dict[int, int]) -> int:
    return sum(1 for n in scores if int(scores[n]) == 1)


def poor_count(scores: Dict[int, int]) -> int:
    return sum(1 for n in scores if int(scores[n]) == 2)


def evaluate(scores: Dict[int, int]) -> dict:
    """Full evaluation of a five-criterion scorecard."""
    total = calc_total(scores)
    return {
        "total": total,
        "percent": calc_percent(total),
        "rating": rating_for(total),
        "flagged": flagged_criteria(scores),
        "critical_count": critical_count(scores),
        "poor_count": poor_count(scores),
    }


def trend(current_total: int, previous_total: Optional[int]) -> str:
    if previous_total is None:
        return "baseline"
    if current_total > previous_total:
        return "improving"
    if current_total < previous_total:
        return "declining"
    return "stable"


# ----------------------------------------------------------- SLA / escalation
def sla_deadline(submitted_at: datetime, sla_hours: int) -> datetime:
    return submitted_at + timedelta(hours=sla_hours)


def should_escalate(status: str, escalated: bool, deadline: datetime, now: datetime) -> bool:
    """Escalate when SLA expired and complaint not resolved/closed/already escalated."""
    if escalated or status in ("RESOLVED", "CLOSED"):
        return False
    return now > deadline


# ----------------------------------------------------------- recurring issues
def recurring_findings(history: Iterable[dict], window: int = 10, threshold: int = 3) -> List[str]:
    """history: newest-first list of dicts {criterion_scores: {1..5: int}}.

    Returns human-readable management-attention messages, e.g.
    'Equipment, Facilities & Supplies has scored 1–2 in 6 of the last 10 inspections.'
    """
    recent = list(history)[:window]
    if len(recent) < 3:
        return []
    messages = []
    for no in range(1, CRITERIA_COUNT + 1):
        bad = sum(1 for h in recent if int(h.get("criterion_scores", {}).get(no, 5)) <= 2)
        if bad >= threshold:
            title = CRITERIA[no]["title"]
            messages.append(f"{title} has scored 1\u20132 in {bad} of the last {len(recent)} inspections.")
    return messages


def alert_conditions(scores: Dict[int, int], multiple_two_threshold: int = 2) -> List[str]:
    """Executive alert triggers for a single inspection."""
    alerts = []
    if critical_count(scores) >= 1:
        alerts.append("Score 1 (Critical) recorded — immediate intervention required.")
    if poor_count(scores) >= multiple_two_threshold:
        alerts.append(f"{poor_count(scores)} criteria scored 2 (Poor) in a single inspection.")
    total = calc_total(scores)
    if rating_for(total) == "CRITICAL":
        alerts.append("Overall inspection rating is CRITICAL.")
    return alerts
