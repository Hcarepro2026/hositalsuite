"""Background delivery dispatch (§39).

Critical operations never wait on slow third-party APIs: complaint/inspection/
booking submission saves instantly, then WhatsApp + SMS queues are processed
on a background thread. In tests, set SYNC_DELIVERY_FOR_TESTS=True to make
delivery synchronous and deterministic.
"""
from __future__ import annotations

import threading

from flask import current_app


def _process(app):
    with app.app_context():
        from . import sms, whatsapp
        from .models import db
        try:
            whatsapp.process_queue(limit=20)
        except Exception as exc:  # noqa: BLE001 — delivery must never crash the app
            app.logger.exception("whatsapp queue error: %s", exc)
            db.session.rollback()
        try:
            sms.process_sms_queue(limit=30)
        except Exception as exc:  # noqa: BLE001
            app.logger.exception("sms queue error: %s", exc)
            db.session.rollback()


def dispatch_delivery():
    """Fire-and-forget processing of WhatsApp + SMS queues."""
    app = current_app._get_current_object()
    if app.config.get("SYNC_DELIVERY_FOR_TESTS"):
        _process(app)
        return
    threading.Thread(target=_process, args=(app,), daemon=True,
                     name="hms-delivery").start()
