"""QR code generation for the public complaint portal."""
from __future__ import annotations

import io

import qrcode


def make_qr_png(data: str) -> bytes:
    img = qrcode.make(data, box_size=10, border=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
