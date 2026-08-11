import os
from zoneinfo import ZoneInfo

# Load private .env file if present (never committed to git)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")


def _data_uri(default_rel: str) -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return "sqlite:///" + os.path.join(DATA_DIR, default_rel)
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        rel = url[len("sqlite:///"):]
        # relative path with a folder part (e.g. data/app.db) resolves from project root
        base = BASE_DIR if os.path.dirname(rel) else DATA_DIR
        return "sqlite:///" + os.path.join(base, rel)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-me")
    SQLALCHEMY_DATABASE_URI = _data_uri("app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Africa/Lagos"))

    UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
    REPORT_DIR = os.path.join(DATA_DIR, "reports")
    BACKUP_DIR = os.environ.get("BACKUP_DIR") or os.path.join(DATA_DIR, "backups")
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))
    MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB evidence photos/files

    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8077")

    # WhatsApp Business Cloud API
    WHATSAPP_MODE = os.environ.get("WHATSAPP_MODE", "sandbox")
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
    WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")
    WHATSAPP_REPORT_TEMPLATE = os.environ.get("WHATSAPP_REPORT_TEMPLATE", "")
    WHATSAPP_SIMULATE_FAILURE = os.environ.get("WHATSAPP_SIMULATE_FAILURE", "0") == "1"

    # SMTP
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "no-reply@localhost")
    SMTP_TLS = os.environ.get("SMTP_TLS", "1") == "1"

    USSD_SHARED_SECRET = os.environ.get("USSD_SHARED_SECRET", "")

    # SMS provider interface (§38): sandbox | termii | twilio | disabled
    SMS_MODE = os.environ.get("SMS_MODE", "sandbox")
    TERMII_API_KEY = os.environ.get("TERMII_API_KEY", "")
    TERMII_SENDER_ID = os.environ.get("TERMII_SENDER_ID", "")
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM = os.environ.get("TWILIO_FROM", "")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 10  # 10 hours

    @classmethod
    def ensure_dirs(cls):
        for d in (DATA_DIR, cls.UPLOAD_DIR, cls.REPORT_DIR, cls.BACKUP_DIR,
                  os.path.join(cls.UPLOAD_DIR, "complaints"),
                  os.path.join(cls.UPLOAD_DIR, "inspections"),
                  os.path.join(cls.UPLOAD_DIR, "logos"),
                  os.path.join(cls.UPLOAD_DIR, "ca")):
            os.makedirs(d, exist_ok=True)
