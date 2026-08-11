"""WhatsApp Business Platform (Meta Cloud API) integration.

Modes
-----
- cloud   : real Meta Graph API (requires WHATSAPP_PHONE_NUMBER_ID + access token)
- sandbox : full workflow simulated locally (default for dev/onboarding)
- disabled: messages queued but never sent (flagged for review)

Media (PDF documents) are uploaded to the Media API first, then sent as
document messages. Delivery receipts arrive via the webhook (/api/v1/whatsapp/webhook).
"""
from __future__ import annotations

import os
from typing import Optional

import requests
from flask import current_app

from .models import WhatsAppMessage, db, now_naive

GRAPH = "https://graph.facebook.com/v19.0"


class WhatsAppError(RuntimeError):
    pass


def mode() -> str:
    return current_app.config.get("WHATSAPP_MODE", "sandbox")


# ------------------------------------------------------------------ media
def _upload_media(pdf_path: str) -> Optional[str]:
    cfg = current_app.config
    url = f"{GRAPH}/{cfg['WHATSAPP_PHONE_NUMBER_ID']}/media"
    with open(pdf_path, "rb") as fh:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {cfg['WHATSAPP_ACCESS_TOKEN']}"},
            data={"messaging_product": "whatsapp", "type": "application/pdf",
                  "filename": os.path.basename(pdf_path)},
            files={"file": (os.path.basename(pdf_path), fh, "application/pdf")},
            timeout=60,
        )
    if resp.status_code not in (200, 201):
        raise WhatsAppError(f"Media upload failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("id")


def _send_document(to_number: str, media_id: str, filename: str, caption: str) -> str:
    cfg = current_app.config
    url = f"{GRAPH}/{cfg['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "document",
        "document": {"id": media_id, "filename": filename, "caption": caption[:1024]},
    }
    resp = requests.post(url, headers={
        "Authorization": f"Bearer {cfg['WHATSAPP_ACCESS_TOKEN']}",
        "Content-Type": "application/json"}, json=payload, timeout=60)
    if resp.status_code not in (200, 201):
        raise WhatsAppError(f"Send failed ({resp.status_code}): {resp.text[:200]}")
    return (resp.json().get("messages") or [{}])[0].get("id", "")


def _send_text(to_number: str, body: str) -> str:
    cfg = current_app.config
    url = f"{GRAPH}/{cfg['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    payload = {"messaging_product": "whatsapp", "to": to_number, "type": "text",
               "text": {"preview_url": False, "body": body[:4000]}}
    resp = requests.post(url, headers={
        "Authorization": f"Bearer {cfg['WHATSAPP_ACCESS_TOKEN']}",
        "Content-Type": "application/json"}, json=payload, timeout=60)
    if resp.status_code not in (200, 201):
        raise WhatsAppError(f"Send failed ({resp.status_code}): {resp.text[:200]}")
    return (resp.json().get("messages") or [{}])[0].get("id", "")


# ------------------------------------------------------------------ queue
def queue_message(org_id: int, to_number: str, body: str, kind: str = "report",
                  media_path: str | None = None, entity_type: str = None,
                  entity_id: int = None, to_user_id: int = None) -> WhatsAppMessage:
    msg = WhatsAppMessage(org_id=org_id, to_number=to_number, body=body, kind=kind,
                          media_path=media_path, entity_type=entity_type, entity_id=entity_id,
                          to_user_id=to_user_id, status="QUEUED")
    db.session.add(msg)
    db.session.commit()
    return msg


def send_message(msg: WhatsAppMessage) -> WhatsAppMessage:
    """Attempt to deliver one queued/failed message. Updates status in place."""
    cfg = current_app.config
    m = mode()
    msg.attempts += 1
    msg.status = "SENDING"
    db.session.commit()
    try:
        if m == "disabled":
            raise WhatsAppError("WhatsApp integration is disabled in configuration.")
        if m == "sandbox":
            if cfg.get("WHATSAPP_SIMULATE_FAILURE") and msg.attempts == 1:
                raise WhatsAppError("Simulated sandbox failure (WHATSAPP_SIMULATE_FAILURE=1).")
            # simulate provider acceptance + delivery receipt
            msg.provider_id = f"SBX-{msg.id:08d}"
            msg.status = "DELIVERED"
            msg.sent_at = now_naive()
            msg.delivered_at = now_naive()
        else:  # cloud
            if msg.media_path and os.path.isabs(msg.media_path) and os.path.exists(msg.media_path):
                media_id = _upload_media(msg.media_path)
                provider = _send_document(msg.to_number, media_id,
                                          os.path.basename(msg.media_path), msg.body)
            else:
                provider = _send_text(msg.to_number, msg.body)
            msg.provider_id = provider
            msg.status = "SENT"          # webhook flips it to DELIVERED
            msg.sent_at = now_naive()
        msg.last_error = None
    except (WhatsAppError, requests.RequestException, OSError) as exc:
        msg.status = "FAILED" if msg.attempts >= 3 else "QUEUED"
        msg.last_error = str(exc)[:400]
    db.session.commit()
    return msg


def process_queue(limit: int = 20) -> int:
    """Send everything queued/failed-with-retries-left. Returns count processed."""
    msgs = (db.session.query(WhatsAppMessage)
            .filter(WhatsAppMessage.status.in_(("QUEUED",)), WhatsAppMessage.attempts < 3)
            .order_by(WhatsAppMessage.created_at).limit(limit).all())
    for m in msgs:
        send_message(m)
    return len(msgs)


def apply_webhook_status(provider_id: str, status: str):
    """Handle delivery status callbacks from Meta (sent / delivered / read / failed)."""
    msg = db.session.query(WhatsAppMessage).filter_by(provider_id=provider_id).first()
    if not msg:
        return
    if status in ("delivered", "read"):
        msg.status = "DELIVERED"
        msg.delivered_at = msg.delivered_at or now_naive()
    elif status == "failed":
        msg.status = "FAILED" if msg.attempts >= 3 else "QUEUED"
        msg.last_error = "Provider reported failure"
    db.session.commit()
