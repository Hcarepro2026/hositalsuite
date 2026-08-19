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
    """Answers this hospital can use: its own, plus the shared library.

    THE HOSPITAL'S OWN COPY ALWAYS WINS.
    ------------------------------------
    When a hospital corrects a shared answer, its correction is saved as its
    OWN copy — the shared original is deliberately left alone so other
    hospitals are not changed. But that left two copies of the same intent in
    play, and the shared (wrong) one could still out-score the corrected one.
    The founder fixed the cafeteria answer, was told "Updated", asked again,
    and heard the old wording. Nothing is more corrosive to trust than that.

    So a shared answer is dropped whenever this hospital has its own version
    of the same intent.
    """
    q = db.session.query(KnowledgeArticle).filter_by(status="approved")
    q = q.filter(db.or_(KnowledgeArticle.org_id.is_(None),
                        KnowledgeArticle.org_id == org_id))
    rows = q.all()
    mine = {a.intent for a in rows if a.org_id is not None}
    if not mine:
        return rows
    return [a for a in rows if a.org_id is not None or a.intent not in mine]


def _phrase_hit(kw: str, text: str) -> bool:
    """True if `kw` appears in `text` as WHOLE WORDS.

    Plain `kw in text` matched across word boundaries, so the trigger
    "are you" (intent how_are_you) fired inside "what ARE YOUr opening hours"
    and beat the correct answer on a tie. Patients asking about opening hours
    were told "I'm doing wonderfully, thank you for asking".
    """
    return re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", text) is not None


# Triggers so generic they describe the SHAPE of a question, not its subject.
# "what does surgery do" was being won by term_general purely because it
# contains "what does". These score at minimum weight so a real subject match
# ("surgery") always wins.
_GENERIC_TRIGGERS = {
    "what does", "what is", "what are", "meaning of", "define", "explain",
    "how do i", "how can i", "can i", "do you", "is there", "tell me about",
    "i need", "i want", "help", "please", "question",
}

# Words that carry NO subject matter. A trigger built only from these is
# question-shape, not topic — e.g. "can i bring", "do you have", "is it
# possible to". Those used to score 9 and 16 respectively and beat real
# subject words, which is how "can i bring a cooking pot" was answered with
# the WEAPONS policy. Structural test beats a hand-maintained list: the KB has
# 7,559 triggers and nobody can enumerate every polite preamble.
# NOTE: "much" is deliberately NOT here. "how much" is not question-shape, it
# means COST - dropping it sent "how much is my bill" to the wrong billing
# answer. Caught by tests/test_chat_ui.py.
_FUNCTION_WORDS = {
    "a", "about", "am", "an", "and", "any", "are", "at", "be", "bring", "can",
    "come", "could", "do", "does", "for", "from", "get", "give", "go", "have",
    "how", "i", "if", "in", "is", "it", "know", "like", "may", "me",
    "must", "my", "need", "of", "on", "or", "please", "possible", "should",
    "tell", "the", "there", "to", "want", "was", "we", "what", "when", "where",
    "which", "who", "why", "will", "with", "would", "you", "your",
}


def _is_generic(kw: str) -> bool:
    """True when a trigger is pure question-shape and names no subject."""
    if kw in _GENERIC_TRIGGERS:
        return True
    parts = kw.split()
    return bool(parts) and all(w in _FUNCTION_WORDS for w in parts)


def _score(article: KnowledgeArticle, text: str) -> int:
    """Relevance of one article to the patient's message.

    Longer trigger phrases score quadratically so a specific multi-word match
    ("opening hours") decisively outranks an incidental short one ("are you").
    """
    best = 0
    total = 0
    for kw in (article.keywords or "").splitlines():
        kw = _norm(kw)   # normalize punctuation so "can't" matches "can t"
        if not kw or not _phrase_hit(kw, text):
            continue
        words = len(kw.split())
        weight = words * words          # 1 word -> 1, 2 -> 4, 3 -> 9
        if _is_generic(kw):
            # Question-shape ("what does"), not subject matter. Scored BELOW a
            # single subject word so "what does SURGERY do" reaches Surgery,
            # not the generic terminology answer.
            weight = 0
            total += 1                  # still counts as breadth, just barely
            continue
        total += weight
        best = max(best, weight)
    # Favour the article with the single most specific match, then breadth.
    return best * 10 + total


# ------------------------------------------------------------------ follow-ups
# A short reply like "yes" is not a question — it is an ANSWER to the offer the
# assistant just made. Scored on its own it matches nothing, falls through to
# the AI, and the AI (which only sees the words, not the offer) invents
# something plausible. That is how "yes" to "shall I book you a morning slot?"
# came back as a phone number instead of the booking page.
_AGREEMENTS = {
    "yes", "yes please", "yes pls", "yeah", "yep", "yup", "ok", "okay", "oky",
    "sure", "please", "please do", "go ahead", "alright", "correct", "fine",
    "do it", "i want", "i would like", "abeg", "na so", "oya", "make i",
    "yes o", "e go better", "no problem", "sounds good", "why not",
}
_REFUSALS = {"no", "no thanks", "no thank you", "nope", "not now", "later",
             "maybe later", "i am fine", "im fine", "no need"}


def is_agreement(text: str) -> bool:
    """Did the patient just say yes to whatever we offered?"""
    t = _norm(text).strip(" .!?")
    if not t or len(t.split()) > 4:
        return False               # a real question, not a bare yes
    return t in _AGREEMENTS


# Somebody trying to TEACH the assistant. The founder typed "Ai please lean
# this ... store it in your memory permanently" and got a lecture about OPD,
# because those words happened to score against the OPD article. The assistant
# cannot learn from a chat message — pretending otherwise is a promise it will
# silently break — so it says so plainly and records the request for a human.
_TEACHING = (
    "remember this", "store it in your memory", "store this in your memory",
    "learn this", "lean this", "keep this in mind", "permanently",
    "from now on", "always say", "always tell", "don't say", "do not say",
    "stop saying", "correct yourself", "update your answer", "you are wrong",
    "that is wrong", "that's wrong", "wrong answer", "it is not true",
)


def is_teaching(text: str) -> bool:
    """Is the user trying to correct or train the assistant?"""
    low = _norm(text)
    return any(p in low for p in _TEACHING)


TEACHING_REPLY = (
    "Thank you — that is exactly the kind of correction that makes me better, "
    "and I have saved it for the team to review. I should be honest with you "
    "though: I cannot change my own answers from this chat. A person has to "
    "update my answer book, and your note is now in the list for them."
)


def is_refusal(text: str) -> bool:
    t = _norm(text).strip(" .!?")
    if not t or len(t.split()) > 4:
        return False
    return t in _REFUSALS


# What "yes" MEANS, depending on what we just offered. The value is the intent
# to answer with, so the follow-up is the hospital's own written words rather
# than something a language model made up on the spot.
_OFFER_FOLLOWUPS = {
    "book":      "book_appointment",
    "complaint": "complaint_start",
    "handoff":   "human_handoff",
}


def followup_for(previous_intent: str, previous_action: str, lang: str = "en",
                 org_id=None):
    """The right answer to a bare 'yes', based on what was offered.

    Returns the same shape as answer(), or None when we genuinely cannot tell
    what was being agreed to — in which case the caller asks the patient to say
    a bit more, which is far better than guessing.
    """
    target = _OFFER_FOLLOWUPS.get(previous_action or "")
    if not target and previous_intent:
        # Any intent whose own call-to-action was an offer to book.
        if previous_intent.endswith("_book") or previous_intent in (
                "hours_clinic", "hours_opd", "book_appointment"):
            target = "book_appointment"
    if not target:
        return None
    for a in _articles_for(org_id):
        if a.intent == target:
            field = LANG_FIELD.get(lang, "en")
            body = getattr(a, field, None) or a.en
            out = body.strip()
            if a.cta:
                out += "  " + a.cta.strip()
            action = "book" if target.endswith("book_appointment") else (
                "complaint" if target == "complaint_start" else "handoff")
            return {"text": out, "article": a, "confidence": 99.0,
                    "action": action}
    return None


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
    intent = best.intent or ""
    # Department intents are named "<dept>_<suffix>" (see kb_departments_full),
    # so match on the suffix too — otherwise a department-specific complaint
    # answer would lose its "Make a complaint" shortcut button.
    if intent in ("book_appointment", "followup_book", "anc_book") or intent.endswith("_book"):
        action = "book"
    elif (intent in ("complaint_start", "bill_dispute")
          or intent.endswith("_complaint") or intent.endswith("_report_fraud")):
        action = "complaint"
    elif best.intent in ("emergency_general", "emergency_chest", "anc_danger",
                         "labour_signs", "newborn_jaundice"):
        action = "emergency"
    elif best.intent == "human_handoff":
        action = "handoff"
    return {"text": out, "article": best, "confidence": float(best_score), "action": action}
