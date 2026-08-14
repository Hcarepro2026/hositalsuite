"""Seed / sync the GLOBAL master dialogue library (org_id NULL).

Idempotent per-intent: on every boot it ADDS any global intent that is missing,
without touching existing rows (so tenant edits, thumbs and hit-counts survive,
and new dialogues ship to existing deployments automatically).
"""
from __future__ import annotations

ALL_MODULES = None


def _all_kb():
    from . import kb_core, kb_depts, kb_extra, kb_extended, kb_part5, kb_part6, kb_part7
    return (list(kb_core.KB) + list(kb_depts.KB) + list(kb_extra.KB) + list(kb_extended.KB)
            + list(kb_part5.KB) + list(kb_part6.KB) + list(kb_part7.KB))


def seed_global_kb(app, quiet: bool = False) -> int:
    from ..models import KnowledgeArticle, db
    with app.app_context():
        existing = {a.intent for a in db.session.query(KnowledgeArticle)
                    .filter_by(org_id=None).all()}
        added = 0
        for entry in _all_kb():
            if entry["intent"] in existing:
                continue
            db.session.add(KnowledgeArticle(
                org_id=None, scope="global", status="approved",
                category=entry["cat"], intent=entry["intent"],
                keywords="\n".join(entry["kw"]),
                en=entry["en"], pidgin=entry.get("pcm"), yo=entry.get("yo"),
                ha=entry.get("ha"), ig=entry.get("ig"), cta=entry.get("cta")))
            added += 1
        if added:
            db.session.commit()
        if not quiet and added:
            kws = sum(len(e["kw"]) for e in _all_kb())
            print(f"[KB] synced +{added} global intents (library now {len(_all_kb())} intents / {kws} triggers)")
        return added


def library_stats(app) -> dict:
    from ..models import KnowledgeArticle, db
    with app.app_context():
        rows = db.session.query(KnowledgeArticle).filter_by(org_id=None).all()
        return {"intents": len(rows),
                "triggers": sum(len(a.keywords.splitlines()) for a in rows)}
