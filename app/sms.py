"""SMS Notification Provider Interface (spec §38).

Primary: Termii (Nigerian provider). Fallback: Twilio. Never hard-coded —
providers are selected by configuration and can be swapped without rewriting
the application. Sandbox mode logs deliveries locally (default for dev).

Every send is queued as an SmsMessage row, attempted with retries, and
logged — failures never break the business flow.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import requests
from flask import current_app

from .models import SmsMessage, db, now_naive


class SmsProviderError(RuntimeError):
    pass


class SmsProvider(ABC):
    name = "base"

    @abstractmethod
    def send(self, to: str, body: str) -> str:
        """Send one SMS; return provider message id. Raise SmsProviderError on failure."""


# ------------------------------------------------------------------ providers
class SandboxSmsProvider(SmsProvider):
    name = "sandbox"

    def send(self, to: str, body: str) -> str:
        return f"SBX-SMS-{now_naive().strftime('%H%M%S')}"


class TermiiSmsProvider(SmsProvider):
    """Termii (Nigeria). https://developer.termii.com"""
    name = "termii"
    URL = "https://api.ng.termii.com/api/sms/send"

    def __init__(self, api_key: str, sender_id: str):
        self.api_key = api_key
        self.sender_id = sender_id

    def send(self, to: str, body: str) -> str:
        if not self.api_key:
            raise SmsProviderError("Termii API key not configured")
        resp = requests.post(self.URL, json={
            "api_key": self.api_key,
            "from": self.sender_id or "HospSuite",
            "to": to,
            "sms": body,
            "type": "plain",
            "channel": "generic",
        }, timeout=30)
        if resp.status_code not in (200, 201):
            raise SmsProviderError(f"Termii error {resp.status_code}: {resp.text[:160]}")
        return str(resp.json().get("message_id", ""))


class TwilioSmsProvider(SmsProvider):
    """Twilio fallback. https://www.twilio.com/docs/sms"""
    name = "twilio"

    def __init__(self, sid: str, token: str, from_number: str):
        self.sid, self.token, self.from_number = sid, token, from_number

    def send(self, to: str, body: str) -> str:
        if not (self.sid and self.token):
            raise SmsProviderError("Twilio credentials not configured")
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        resp = requests.post(url, auth=(self.sid, self.token),
                             data={"From": self.from_number, "To": to, "Body": body}, timeout=30)
        if resp.status_code not in (200, 201):
            raise SmsProviderError(f"Twilio error {resp.status_code}: {resp.text[:160]}")
        return resp.json().get("sid", "")


# ------------------------------------------------------------------ factory
def get_provider() -> SmsProvider:
    """Pick the configured provider with automatic fallback (§40)."""
    cfg = current_app.config
    mode = cfg.get("SMS_MODE", "sandbox")
    if mode == "termii":
        p = TermiiSmsProvider(cfg.get("TERMII_API_KEY", ""), cfg.get("TERMII_SENDER_ID", ""))
        try:
            if not cfg.get("TERMII_API_KEY"):
                raise SmsProviderError("no key")
            return p
        except SmsProviderError:
            pass  # fall through to twilio/sandbox
    if mode in ("termii", "twilio"):
        if cfg.get("TWILIO_ACCOUNT_SID"):
            return TwilioSmsProvider(cfg.get("TWILIO_ACCOUNT_SID", ""),
                                     cfg.get("TWILIO_AUTH_TOKEN", ""),
                                     cfg.get("TWILIO_FROM", ""))
    if mode == "disabled":
        return None
    return SandboxSmsProvider()


# ------------------------------------------------------------------ queue
def queue_sms(org_id: int, to_number: str, body: str, kind: str = "alert",
              entity_type: str = None, entity_id: int = None) -> SmsMessage:
    msg = SmsMessage(org_id=org_id, to_number=to_number, body=body[:480], kind=kind,
                     entity_type=entity_type, entity_id=entity_id)
    db.session.add(msg)
    db.session.commit()
    return msg


def send_sms(msg: SmsMessage) -> SmsMessage:
    msg.attempts += 1
    provider = get_provider()
    if provider is None:
        msg.status = "FAILED"
        msg.last_error = "SMS disabled in configuration"
        db.session.commit()
        return msg
    msg.provider = provider.name
    try:
        msg.provider_id = provider.send(msg.to_number, msg.body)
        msg.status = "SENT"
        msg.sent_at = now_naive()
        msg.last_error = None
    except (SmsProviderError, requests.RequestException, OSError) as exc:
        msg.status = "FAILED" if msg.attempts >= 3 else "QUEUED"
        msg.last_error = str(exc)[:400]
    db.session.commit()
    return msg


def process_sms_queue(limit: int = 30) -> int:
    msgs = (db.session.query(SmsMessage)
            .filter(SmsMessage.status == "QUEUED", SmsMessage.attempts < 3)
            .order_by(SmsMessage.created_at).limit(limit).all())
    for m in msgs:
        send_sms(m)
    return len(msgs)
