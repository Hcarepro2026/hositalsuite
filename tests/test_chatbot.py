"""Phase A+B tests: premium patient assistant + KB multi-tenant + guardrails."""
import json

from app.chatbot import engine
from app.chatbot.seed_kb import seed_global_kb
from app.models import KnowledgeArticle, db


def _kb(app):
    seed_global_kb(app)


def test_kb_seeds_global_master(app, seeded):
    _kb(app)
    with app.app_context():
        n = db.session.query(KnowledgeArticle).filter_by(org_id=None, status="approved").count()
        assert n >= 55
        kws = sum(len(a.keywords.splitlines()) for a in
                  db.session.query(KnowledgeArticle).filter_by(org_id=None).all())
        assert kws >= 500, kws   # large trigger surface (500–1000 target)


def test_retrieval_premium_answers(app, seeded):
    _kb(app)
    with app.app_context():
        r = engine.answer("good morning, how are you today?", "en", seeded["org"])
        assert r and "welcome" in r["text"].lower()
        r = engine.answer("how much is the lab test please", "en", seeded["org"])
        assert r and r["article"].category in ("bills", "laboratory")
        r = engine.answer("i want to book ANC, i am pregnant", "en", seeded["org"])
        assert r and r["action"] == "book"
        r = engine.answer("my chest is hurting and i can't breathe", "en", seeded["org"])
        assert r and r["action"] == "emergency"


def test_clinical_guardrail_never_diagnoses(app, seeded):
    _kb(app)
    with app.app_context():
        r = engine.answer("diagnose me, which drug should i take for malaria?", "en", seeded["org"])
        assert r and r["action"] == "clinical"
        assert "not able to diagnose" in r["text"]
        assert r["article"] is None


def test_pidgin_and_local_languages(app, seeded):
    _kb(app)
    with app.app_context():
        r = engine.answer("hello, good morning", "pcm", seeded["org"])
        assert r and "How far" in r["text"]
        r = engine.answer("hello", "yo", seeded["org"])
        assert r and r["text"]  # Yoruba present for greet
        r = engine.answer("good morning", "ha", seeded["org"])
        assert r and r["text"]


def test_unanswered_then_handoff(client, app, seeded):
    _kb(app)
    r = client.post("/api/chat", json={"text": "quantum flux capacitor warranty", "lang": "en"})
    d = r.get_json()
    assert d["answered"] is False
    r = client.post("/chat/handoff", json={"session": d["session"]})
    assert r.get_json()["ok"] is True


def test_feedback_updates_counts(client, app, seeded):
    _kb(app)
    d = client.post("/api/chat", json={"text": "what are your opening hours?", "lang": "en"}).get_json()
    assert d["answered"] is True
    art_id = None
    with app.app_context():
        from app.models import ChatMessage
        m = db.session.get(ChatMessage, d["msg_id"])
        art_id = m.article_id
        before = db.session.get(KnowledgeArticle, art_id).thumbs_up or 0
    client.post("/chat/feedback", json={"msg_id": d["msg_id"], "rating": "up"})
    with app.app_context():
        after = db.session.get(KnowledgeArticle, art_id).thumbs_up
        assert after == before + 1


def test_tenant_submission_pending_and_promote(client, app, seeded):
    _kb(app)
    from conftest import login, csrf
    login(client, "md")   # MD can submit tenant dialogues (pending), not approve
    tok = csrf(client, "/admin/kb")
    client.post("/admin/kb/add", data={
        "_csrf": tok, "category": "custom", "intent": "parking",
        "keywords": "parking, car park, where to park",
        "en": "We have free patient parking right beside the main gate.",
        "pidgin": "We get free parking beside the main gate o."}, follow_redirects=True)
    with app.app_context():
        a = db.session.query(KnowledgeArticle).filter_by(intent="parking").first()
        assert a.status == "pending" and a.org_id == seeded["org"]
    # MD cannot approve (super only)
    r = client.post(f"/admin/kb/{a.id}/approve", data={"_csrf": tok})
    assert r.status_code == 403
    # Super approves + promotes to global (learning loop)
    login(client, "admin")
    tok = csrf(client, "/admin/kb?scope=pending")
    client.post(f"/admin/kb/{a.id}/approve", data={"_csrf": tok})
    client.post(f"/admin/kb/{a.id}/promote", data={"_csrf": tok})
    with app.app_context():
        a = db.session.query(KnowledgeArticle).filter_by(intent="parking").first()
        assert a.status == "approved" and a.org_id is None and a.scope == "global"
