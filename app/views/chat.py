"""Public patient-assistant chat (web) + feedback + human handoff."""
from __future__ import annotations

from flask import (Blueprint, current_app, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from .. import services
from ..audit import audit
from ..chatbot import engine
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
