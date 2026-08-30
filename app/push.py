"""
Web Push service — works even when app closed like alarm, free, cost saver
--------------------------------------------------------------------------
Uses pywebpush + VAPID to send push to browser, even when app closed.
Server wakes Service Worker, SW shows notification with sound/vibrate/requireInteraction.

Multi-tenant: per org_id, per user or anonymous patient via access_key.
Browser support: Chrome, Firefox, Edge, Opera, Samsung Internet, Safari 16.4+ (PWA installed)
Feature phone fallback: if no push support, we use TV + voice + SMS only for emergency.

Cost saving: push is FREE vs SMS ₦3-4 each. 80-90% saving.

Loading time: push payload <1KB, encrypted, fast on slow Africa internet.
"""

from __future__ import annotations

import json
from typing import Dict, Any

from flask import current_app

from .models import db, now_naive

def _get_vapid_for_org(org_id: int | None = None) -> tuple[str, str, str]:
    """Per-org VAPID if set in settings, else global env — multi-hospital.

    Each hospital can have own VAPID keys via /admin/settings → VAPID_PUBLIC/PRIVATE/SUBJECT
    This allows per-org branding + push that shows hospital name/logo on home screen.
    """
    cfg = current_app.config
    # Try per-org settings first
    if org_id:
        try:
            from . import services
            pub = services.get_setting(org_id, "vapid_public_key")
            priv = services.get_setting(org_id, "vapid_private_key")
            subj = services.get_setting(org_id, "vapid_subject") or cfg.get("VAPID_SUBJECT", "mailto:admin@hospital.local")
            if pub and priv:
                return pub, priv, subj
        except Exception:
            pass
    # Fallback global
    return (cfg.get("VAPID_PUBLIC_KEY", ""), cfg.get("VAPID_PRIVATE_KEY", ""), cfg.get("VAPID_SUBJECT", "mailto:admin@hospital.local"))

def is_configured(org_id: int | None = None) -> bool:
    """Check if VAPID keys set — per-org or global."""
    pub, priv, _ = _get_vapid_for_org(org_id)
    return bool(pub and priv)

def get_vapid_public(org_id: int | None = None) -> str:
    """Public key for client — per-org if set, else global. Used in manifest + push subscribe."""
    pub, _, _ = _get_vapid_for_org(org_id)
    return pub

def _detect_browser(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "edg" in ua:
        return "edge"
    if "opr" in ua or "opera" in ua:
        return "opera"
    if "samsungbrowser" in ua:
        return "samsung"
    if "ucbrowser" in ua or "uc browser" in ua:
        return "uc"
    if "firefox" in ua or "fxios" in ua:
        return "firefox"
    if "safari" in ua and "chrome" not in ua:
        return "safari"
    if "chrome" in ua:
        return "chrome"
    return "unknown"

def queue_push(org_id: int, subscription_id: int, title: str, body: str, url: str = "/",
               category: str = "general", priority: str = "NORMAL",
               require_interaction: bool = False, vibrate: list | None = None,
               actions: list | None = None) -> Any:
    """Queue a push message — like queue_sms, but free and works closed."""
    from .models_v2 import PushQueue
    if vibrate is None:
        # Default vibrate per priority — premium haptic
        if priority == "EMERGENCY":
            vibrate = [500, 200, 500, 200, 1000]
        elif priority in ("CRITICAL", "HIGH"):
            vibrate = [300, 100, 300, 100, 300]
        else:
            vibrate = [200, 100, 200]
    if actions is None:
        actions = [{"action": "view", "title": "View"}, {"action": "dismiss", "title": "Dismiss"}]

    row = PushQueue(
        org_id=org_id,
        subscription_id=subscription_id,
        title=title[:120],
        body=body[:500],
        url=url[:300],
        category=category[:20],
        priority=priority[:10],
        require_interaction=require_interaction,
        vibrate=json.dumps(vibrate),
        actions=json.dumps(actions),
        status="QUEUED"
    )
    db.session.add(row)
    db.session.flush()
    return row

def send_push_to_subscription(subscription, payload: Dict[str, Any]) -> tuple[bool, str]:
    """Send one push via pywebpush — per-org VAPID, returns (ok, error)."""
    org_id = getattr(subscription, 'org_id', None)
    if not is_configured(org_id):
        return False, "VAPID not configured"

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return False, "pywebpush not installed — pip install pywebpush"

    vapid_public, vapid_private, vapid_subject = _get_vapid_for_org(org_id)

    # Build subscription info for pywebpush
    sub_info = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth
        }
    }

    # Payload is JSON, <1KB for slow internet
    data = json.dumps(payload, ensure_ascii=False)

    try:
        webpush(
            subscription_info=sub_info,
            data=data,
            vapid_private_key=vapid_private,
            vapid_claims={"sub": vapid_subject, "aud": ""},
            ttl=payload.get("ttl", 86400)
        )
        return True, ""
    except Exception as exc:
        # WebPushException has response
        err = str(exc)[:400]
        # If 410 Gone, subscription expired — deactivate
        if "410" in err or "expired" in err.lower() or "invalid" in err.lower():
            try:
                subscription.is_active = False
                db.session.commit()
            except Exception:
                db.session.rollback()
        return False, err

def process_push_queue(limit: int = 30):
    """Process queued pushes — called by scheduler every 30s, like SMS queue.
    
    Multi-hospital: per-org VAPID, so check is_configured per row org_id, not just global.
    """
    from .models_v2 import PushQueue, PushSubscription
    sent = 0
    try:
        rows = db.session.query(PushQueue).filter_by(status="QUEUED").order_by(PushQueue.created_at.asc()).limit(limit).all()
        if not rows:
            return 0
        # Quick check: if no global and no per-org configured, skip to avoid DB churn, but still try per-row
        # We don't early return on global alone — per-org may be configured
        for row in rows:
            sub = db.session.get(PushSubscription, row.subscription_id)
            if not sub or not sub.is_active:
                row.status = "FAILED"
                row.last_error = "Subscription inactive"
                continue
            # Per-org VAPID check — multi-hospital
            if not is_configured(row.org_id):
                # Try global fallback too
                if not is_configured():
                    row.last_error = "VAPID not configured for org"
                    # Keep QUEUED for retry if attempts <3, else fail
                    row.attempts = (row.attempts or 0) + 1
                    if row.attempts >= 3:
                        row.status = "FAILED"
                    continue
            payload = {
                "title": row.title,
                "body": row.body,
                "url": row.url,
                "category": row.category,
                "priority": row.priority,
                "requireInteraction": row.require_interaction,
                "vibrate": json.loads(row.vibrate) if row.vibrate else [200,100,200],
                "actions": json.loads(row.actions) if row.actions else [],
                "id": row.id,
                "tag": f"hs-{row.category}-{row.org_id}",
                "ttl": 86400
            }
            ok, err = send_push_to_subscription(sub, payload)
            row.attempts = (row.attempts or 0) + 1
            if ok:
                row.status = "SENT"
                row.sent_at = now_naive()
                sub.last_used_at = now_naive()
                sent += 1
            else:
                row.last_error = err[:400]
                if row.attempts >= 3:
                    row.status = "FAILED"
                # else keep QUEUED for retry
        db.session.commit()
    except Exception as exc:
        current_app.logger.exception("push queue failed: %s", exc)
        db.session.rollback()
    return sent

def notify_user(org_id: int, user_id: int, title: str, body: str, url: str = "/", category: str = "general", priority: str = "NORMAL", require_interaction: bool = False):
    """Helper: queue push to all active subscriptions for a user."""
    from .models_v2 import PushSubscription
    subs = db.session.query(PushSubscription).filter_by(org_id=org_id, user_id=user_id, is_active=True).all()
    for sub in subs:
        queue_push(org_id, sub.id, title, body, url=url, category=category, priority=priority, require_interaction=require_interaction)

def notify_patient(org_id: int, access_key: str, title: str, body: str, url: str = "/", category: str = "queue", priority: str = "HIGH", require_interaction: bool = True):
    """Helper: queue push to patient anonymous subscription via access_key."""
    from .models_v2 import PushSubscription
    subs = db.session.query(PushSubscription).filter_by(org_id=org_id, patient_access_key=access_key, is_active=True).all()
    for sub in subs:
        queue_push(org_id, sub.id, title, body, url=url, category=category, priority=priority, require_interaction=require_interaction)
