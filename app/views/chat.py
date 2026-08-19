"""Public patient-assistant chat (web) + feedback + human handoff."""
from __future__ import annotations

from flask import (Blueprint, current_app, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from .. import services
from ..audit import audit
from ..chatbot import engine, quickedit
from ..models import (ChatFeedback, ChatMessage, ChatSession, Organization, db,
                      now_naive)
from ..security import csrf_exempt, rate_limit

bp = Blueprint("chat", __name__)


def _org():
    """Tenant for this request (see services.current_org)."""
    from ..services import current_org
    return current_org()


@bp.get("/chat")
@rate_limit(limit=60, window=60.0)
def chat_page():
    org = _org()
    return render_template("chat.html", org=org)


@bp.post("/api/chat")
@csrf_exempt("chat.chat_api")
@rate_limit(limit=40, window=60.0)
def chat_api():
    org = _org()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    # Coerce defensively: a non-string "text" (a number, a list, null) used to
    # raise AttributeError and return a 500 to the patient.
    raw = data.get("text")
    text = (raw if isinstance(raw, str) else ("" if raw is None else str(raw))).strip()
    text = text[:2000]                     # bound the work the retrieval engine does
    lang = data.get("lang")
    lang = lang if isinstance(lang, str) and lang in ("en", "yo", "ha", "ig", "pcm") else "en"
    session_id = data.get("session")
    session_id = session_id if isinstance(session_id, int) else None
    if not text:
        return jsonify(error="empty"), 400
    sess = db.session.get(ChatSession, session_id) if session_id else None
    if sess is None:
        sess = ChatSession(org_id=org.id if org else None, lang=lang, channel="web")
        db.session.add(sess)
        db.session.flush()

    # ---- SUPER ADMIN CORRECTING AN ANSWER, IN THE CHAT.
    # Checked before ANYTHING else so a correction is never mistaken for a
    # question. Two locks: signed in as Super Admin AND the secret code. This
    # endpoint is public and CSRF-exempt, so a code on its own would put the
    # hospital's answers one lucky guess away from a stranger.
    if quickedit.looks_like_edit(text):
        handled, result = quickedit.apply(org.id if org else None,
                                          current_user, text)
        if handled:
            if isinstance(result, dict):
                audit("KB_QUICK_EDIT", "knowledge_article",
                      result.get("article_id"),
                      {"intent": result.get("intent"),
                       "scope": result.get("scope"),
                       "replaced": result.get("old", "")[:200]})
                reply = result["message"]
            else:
                reply = result
            bot = ChatMessage(session_id=sess.id, role="bot", text=reply)
            db.session.add(bot)
            db.session.commit()
            return jsonify(session=sess.id, answered=True, reply=reply,
                           msg_id=bot.id, intent="kb_quick_edit")

    # ---- SOMEBODY TEACHING THE ASSISTANT.
    # "Ai please learn this... store it permanently" used to score against
    # whatever article shared a word with it (an OPD lecture, in the founder's
    # case). The assistant cannot learn from a chat message, and pretending it
    # can is a promise it will silently break. Say so, and record it.
    if engine.is_teaching(text):
        db.session.add(ChatMessage(session_id=sess.id, role="user", text=text,
                                   intent="teaching_note", unanswered=True))
        db.session.flush()
        bot = ChatMessage(session_id=sess.id, role="bot",
                          text=engine.TEACHING_REPLY)
        db.session.add(bot)
        db.session.commit()
        return jsonify(session=sess.id, answered=True,
                       reply=engine.TEACHING_REPLY, msg_id=bot.id,
                       intent="teaching_note")

    # ---- FOLLOW-UP FIRST. "Yes" is not a question, it is an answer to the
    # offer we just made. Scored on its own it matches nothing, so it used to
    # fall through to the AI, which saw only the word "yes" and invented a
    # plausible reply — that is how "yes, book me a morning slot" came back as
    # a phone number instead of the booking page.
    res = None
    if engine.is_agreement(text) or engine.is_refusal(text):
        last = (db.session.query(ChatMessage)
                .filter_by(session_id=sess.id, role="user")
                .order_by(ChatMessage.id.desc()).first())
        prev_intent = (last.intent if last else "") or ""
        if engine.is_refusal(text):
            res = {"text": ("No problem at all. I'm here whenever you need "
                            "me — just ask."),
                   "article": None, "confidence": 99.0, "action": None}
        else:
            res = engine.followup_for(prev_intent, prev_intent,
                                      lang=lang,
                                      org_id=org.id if org else None)
            if res is None:
                # We genuinely cannot tell what was agreed to. ASKING is far
                # better than guessing and being confidently wrong.
                res = {"text": ("Happy to help — could you tell me what you'd "
                                "like me to do? For example \u201cbook an "
                                "appointment\u201d or \u201cspeak to "
                                "someone\u201d."),
                       "article": None, "confidence": 99.0, "action": None}

    if res is None:
        res = engine.answer(text, lang=lang, org_id=org.id if org else None)

    # ---- AI fallback: only when the curated library has no confident answer.
    # The hospital's own words always win; AI fills the long tail.
    if res is None:
        from ..chatbot import ai
        recent = (db.session.query(ChatMessage)
                  .filter_by(session_id=sess.id)
                  .order_by(ChatMessage.id.desc()).limit(4).all())
        history = [{"role": m.role, "text": m.text} for m in reversed(recent)]
        try:
            got = ai.answer(text, org=org, lang=lang, history=history)
        except Exception:                                # noqa: BLE001 - never break chat
            current_app.logger.exception("AI fallback failed")
            got = None
        if got:
            db.session.add(ChatMessage(session_id=sess.id, role="user", text=text,
                                       intent="ai_fallback", unanswered=False))
            db.session.flush()
            bot = ChatMessage(session_id=sess.id, role="bot", text=got["text"])
            db.session.add(bot)
            db.session.commit()
            return jsonify(session=sess.id, answered=True, reply=got["text"],
                           msg_id=bot.id, source=got["provider"])

    if res is None:
        db.session.add(ChatMessage(session_id=sess.id, role="user", text=text,
                                   unanswered=True))
        db.session.commit()
        return jsonify(session=sess.id, answered=False,
                       reply=("I want to get this exactly right, and I don't have a perfect answer for "
                              "that yet. I can connect you to our front desk, or try one of the quick "
                              "topics below. Shall I get a human to help?"))
    msg = ChatMessage(session_id=sess.id, role="user", text=text,
                      intent=res["article"].intent if res["article"] else res.get("action"),
                      confidence=res["confidence"],
                      article_id=res["article"].id if res["article"] else None)
    db.session.add(msg)
    db.session.flush()
    bot = ChatMessage(session_id=sess.id, role="bot", text=res["text"],
                      article_id=res["article"].id if res["article"] else None)
    db.session.add(bot)
    db.session.commit()
    return jsonify(session=sess.id, answered=True, reply=res["text"],
                   action=res.get("action"), msg_id=bot.id,
                   intent=res["article"].intent if res["article"] else None)


@bp.post("/chat/feedback")
@csrf_exempt("chat.chat_feedback")
@rate_limit(limit=60, window=60.0)
def chat_feedback():
    data = request.get_json(silent=True) or {}
    msg_id = data.get("msg_id")
    rating = "up" if data.get("rating") == "up" else "down"
    msg = db.session.get(ChatMessage, msg_id or 0)
    if not msg:
        return jsonify(error="not found"), 404
    db.session.add(ChatFeedback(message_id=msg.id, article_id=msg.article_id, rating=rating))
    if msg.article_id:
        from ..models import KnowledgeArticle
        art = db.session.get(KnowledgeArticle, msg.article_id)
        if art:
            if rating == "up":
                art.thumbs_up = (art.thumbs_up or 0) + 1
            else:
                art.thumbs_down = (art.thumbs_down or 0) + 1
    db.session.commit()
    return jsonify(ok=True)


@bp.post("/chat/handoff")
@csrf_exempt("chat.chat_handoff")
@rate_limit(limit=10, window=120.0)
def chat_handoff():
    """Human handoff: notify the Admin Manager on duty + create a chat-escalation note."""
    from .. import notifications
    org = _org()
    data = request.get_json(silent=True) or {}
    session_id = data.get("session")
    sess = db.session.get(ChatSession, session_id or 0)
    if sess:
        sess.handed_off = True
    duty = services.on_duty(org.id, now_naive().date()) if org else None
    ctx = {"ref": f"CHAT-{session_id or 'web'}", "dept": "Front Desk", "category": "Chat handoff",
           "hospital": org.name if org else "", "sla": ""}
    if org and duty:
        notifications.notify(org.id, duty, "complaint_new_admin", ctx, channels=["inapp"],
                             entity_type="chat", entity_id=session_id or 0)
    db.session.commit()
    audit("CHAT_HANDOFF", "chat", session_id or 0, {})
    return jsonify(ok=True,
                   message="Thank you for your patience — I've alerted our front desk and a team "
                           "member will be with you shortly. You're in good hands.")
