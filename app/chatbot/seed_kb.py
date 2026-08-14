"""Seed the GLOBAL master dialogue library (org_id NULL) on first run."""
from __future__ import annotations


def seed_global_kb(app) -> int:
    from ..models import KnowledgeArticle, db
    from . import kb_core, kb_depts, kb_extra
    with app.app_context():
        if db.session.query(KnowledgeArticle).filter_by(org_id=None).first():
            return 0
        count = 0
        for entry in list(kb_core.KB) + list(kb_depts.KB) + list(kb_extra.KB):
            db.session.add(KnowledgeArticle(
                org_id=None, scope="global", status="approved",
                category=entry["cat"], intent=entry["intent"],
                keywords="\n".join(entry["kw"]),
                en=entry["en"], pidgin=entry.get("pcm"), yo=entry.get("yo"),
                ha=entry.get("ha"), ig=entry.get("ig"), cta=entry.get("cta")))
            count += 1
        db.session.commit()
        kws = sum(len(e["kw"]) for e in list(kb_core.KB) + list(kb_depts.KB) + list(kb_extra.KB))
        print(f"[KB] seeded {count} global intents / {kws} keyword triggers")
        return count
