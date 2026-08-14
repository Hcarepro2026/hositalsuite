"""Chatbot retrieval engine — premium, safe, cheap.

Layer 1 (always on, ~₦0): keyword/BM25-style retrieval over the multi-tenant KB.
Clinical guardrail: diagnosis/prescription-seeking messages get a safe redirect,
never a diagnosis (WHO AI-ethics + product rule).
"""
from __future__ import annotations

import re

from ..models import KnowledgeArticle, db

LANG_FIELD = {"en": "en", "pcm": "pidgin", "yo": "yo", "ha": "ha", "ig": "ig"}

# Patterns that seek diagnosis/prescription -> refuse & redirect to care.
CLINICAL_SEEK = [
    r"diagnos", r"what (disease|illness|sickness) do i have", r"which (drug|medicine|tablet)",
    r"prescribe", r"medicine for", r"drug for", r"what is wrong with me", r"do i have (cancer|malaria|diabetes|hiv)",
    r"dosage", r"how many (tablets|mg)",
]

SAFE_CLINICAL = (
    "I'd love to help, but I'm not able to diagnose conditions or recommend medicines — that needs a "
    "clinician who can examine you properly, and you deserve nothing less. I can book you into the right "
    "clinic right now, or if it's urgent please head to our 24/7 A&E. Shall I book you in?"
)

SAFE_CLINICAL_PCM = (
    "I go love to help, but I no fit diagnose or recommend medicine o — na doctor wey go examine you properly "
    "suppo do am, and you deserve the best. I fit book you into the right clinic now now, or if e urgent abeg "
    "go our A&E wey dey open 24/7. Make I book you?"
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", (text or "").lower()).strip()


def is_clinical_seek(text: str) -> bool:
    t = _norm(text)
    return any(re.search(p, t) for p in CLINICAL_SEEK)


def _articles_for(org_id):
    q = db.session.query(KnowledgeArticle).filter_by(status="approved")
    q = q.filter(db.or_(KnowledgeArticle.org_id.is_(None), KnowledgeArticle.org_id == org_id))
    return q.all()


def _score(article: KnowledgeArticle, text: str) -> int:
    hits = 0
    for kw in (article.keywords or "").splitlines():
        kw = _norm(kw)   # normalize punctuation so "can't" matches "can t"
        if kw and kw in text:
            # longer, more specific triggers weigh more
            hits += max(1, len(kw.split()))
    return hits


def answer(text: str, lang: str = "en", org_id=None):
    """Return dict(text, article, confidence, action) or None if unanswered."""
    t = _norm(text)
    if is_clinical_seek(t):
        return {"text": SAFE_CLINICAL_PCM if lang == "pcm" else SAFE_CLINICAL,
                "article": None, "confidence": 1.0, "action": "clinical"}

    best, best_score = None, 0
    for a in _articles_for(org_id):
        s = _score(a, t)
        if s > best_score:
            best, best_score = a, s
    if best is None or best_score < 1:
        return None

    field = LANG_FIELD.get(lang, "en")
    body = getattr(best, field, None) or getattr(best, "yo", None) or best.en
    out = body.strip()
    if best.cta:
        out += "  " + best.cta.strip()
    best.hit_count = (best.hit_count or 0) + 1
    db.session.commit()
    action = None
    if best.intent in ("book_appointment", "followup_book", "anc_book"):
        action = "book"
    elif best.intent in ("complaint_start", "bill_dispute"):
        action = "complaint"
    elif best.intent in ("emergency_general", "emergency_chest", "anc_danger"):
        action = "emergency"
    return {"text": out, "article": best, "confidence": float(best_score), "action": action}
