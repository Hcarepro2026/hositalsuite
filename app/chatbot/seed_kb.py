"""Seed / sync the GLOBAL master dialogue library (org_id NULL).

Idempotent per-intent: on every boot it ADDS any global intent that is missing,
without touching existing rows (so tenant edits, thumbs and hit-counts survive,
and new dialogues ship to existing deployments automatically).
"""
from __future__ import annotations

ALL_MODULES = None


def _all_kb():
    from . import (kb_core, kb_departments_full, kb_depts, kb_extra, kb_extended,
                   kb_part5, kb_part6, kb_part7, kb_app_master)
    return (list(kb_core.KB) + list(kb_depts.KB) + list(kb_extra.KB) + list(kb_extended.KB)
            + list(kb_part5.KB) + list(kb_part6.KB) + list(kb_part7.KB)
            + list(kb_departments_full.KB) + list(kb_app_master.KB))


def seed_global_kb(app, quiet: bool = False) -> int:
    from ..models import KnowledgeArticle, db
    with app.app_context():
        existing = {a.intent: a for a in db.session.query(KnowledgeArticle)
                    .filter_by(org_id=None).all()}
        added = updated = 0
        for entry in _all_kb():
            row = existing.get(entry["intent"])
            if row is None:
                db.session.add(KnowledgeArticle(
                    org_id=None, scope="global", status="approved",
                    category=entry["cat"], intent=entry["intent"],
                    keywords="\n".join(entry["kw"]),
                    en=entry["en"], pidgin=entry.get("pcm"), yo=entry.get("yo"),
                    ha=entry.get("ha"), ig=entry.get("ig"), cta=entry.get("cta")))
                added += 1
                continue
            # REFRESH existing global rows when the shipped library changes.
            # Previously we skipped them entirely, so improved wording and NEW
            # TRIGGERS never reached a deployed hospital — a fix could be
            # written, tested, deployed, and still not work in production.
            # Tenant-authored rows (org_id set) are never touched.
            new_kw = "\n".join(entry["kw"])
            changed = (row.keywords != new_kw or row.en != entry["en"]
                       or row.cta != entry.get("cta")
                       or row.pidgin != entry.get("pcm"))
            if changed:
                row.keywords = new_kw
                row.en = entry["en"]
                row.pidgin = entry.get("pcm")
                row.yo = entry.get("yo") or row.yo
                row.ha = entry.get("ha") or row.ha
                row.ig = entry.get("ig") or row.ig
                row.cta = entry.get("cta")
                row.category = entry["cat"]
                updated += 1
        if added or updated:
            db.session.commit()
        if not quiet and (added or updated):
            kws = sum(len(e["kw"]) for e in _all_kb())
            print(f"[KB] synced +{added} new / {updated} updated global intents "
                  f"(library now {len(_all_kb())} intents / {kws} triggers)")
        return added + updated


def library_stats(app) -> dict:
    from ..models import KnowledgeArticle, db
    with app.app_context():
        rows = db.session.query(KnowledgeArticle).filter_by(org_id=None).all()
        return {"intents": len(rows),
                "triggers": sum(len(a.keywords.splitlines()) for a in rows)}
