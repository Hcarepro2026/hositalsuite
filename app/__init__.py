"""Application factory."""
from __future__ import annotations

import os

from flask import Flask, g, render_template, request
from flask_login import LoginManager

from .config import Config
from .models import User, db

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."


@login_manager.user_loader
def load_user(user_id: str):
    u = db.session.get(User, int(user_id))
    return u if u and u.active else None


def create_app(config_object=None, scheduler: bool = True) -> Flask:
    Config.ensure_dirs()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_object or Config)

    db.init_app(app)
    login_manager.init_app(app)

    from .security import register_security_hooks
    from .views.auth import bp as auth_bp
    from .views.main import bp as main_bp
    from .views.inspections import bp as insp_bp
    from .views.complaints import bp as comp_bp
    from .views.bookings import bp as book_bp
    from .views.queue import bp as queue_bp
    from .views.feedback import bp as fb_bp
    from .views.chat import bp as chat_bp
    from .views.roster import bp as roster_bp
    from .views.admincp import bp as admin_bp
    from .views.reports import bp as reports_bp
    from .views.api import bp as api_bp

    for blueprint in (auth_bp, main_bp, insp_bp, comp_bp, book_bp, queue_bp, fb_bp,
                      chat_bp, roster_bp, admin_bp, reports_bp, api_bp):
        app.register_blueprint(blueprint)

    register_security_hooks(app)

    with app.app_context():
        # SQLite hardening: WAL lets the scheduler thread and web requests write
        # concurrently without "database is locked" errors; busy_timeout makes
        # writers wait instead of failing instantly.
        if str(db.engine.url).startswith("sqlite"):
            from sqlalchemy import event

            @event.listens_for(db.engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA busy_timeout=15000")
                cur.close()

        db.create_all()
        from .migrate import ensure_schema
        ensure_schema()

        # First-boot bootstrap on free hosts with no shell access (Render free):
        # AUTO_SEED=1 seeds ONLY an empty database; credentials printed once to logs.
        if os.environ.get("AUTO_SEED") == "1":
            from .seeddata import auto_seed
            auto_seed(app)

        # Load the global master dialogue library for the patient assistant.
        from .chatbot.seed_kb import seed_global_kb
        seed_global_kb(app)

    @app.context_processor
    def inject_globals():
        from .security import csrf_token
        from .services import org_settings_bundle
        from . import i18n
        bundle = {}
        u = getattr(g, "_login_user", None) or (request and getattr(request, "_cached_user", None))
        try:
            from flask_login import current_user
            u = current_user if current_user.is_authenticated else None
        except Exception:
            u = None
        if u is not None:
            bundle = org_settings_bundle(u.org_id)
        lang = i18n.get_lang()
        return dict(csrf_token=csrf_token, settings=bundle, app_version="1.0.0",
                    _=i18n.translate, lang=lang, langs=i18n.LANGS,
                    speech_lang=i18n.speech_tag(lang))

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404,
                               message="The page you requested was not found."), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403,
                               message="You do not have permission to access this page."), 403

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("error.html", code=500,
                               message="Something went wrong on our side. The technical team has been notified."), 500

    if scheduler and os.environ.get("DISABLE_SCHEDULER") != "1":
        from .scheduler import start_scheduler
        start_scheduler(app)

    return app
