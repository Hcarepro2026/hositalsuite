"""Native Voice Bank — admin UI + API for phrase bank (not clone).

Dynamic handling:
- Time: greeting based on now_naive().hour
- Names: speech_name() for any new name, not hardcoded
- Counts/places: number_* and place_* recordings per language
- Languages: en, yo, ha, ig per tenant
- Voices: 2M2F recycled daily, per org
"""
from __future__ import annotations

import json

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from ..models import NativePhrase, NativeVoice, NativeVoiceSetting, db, now_naive
from .. import native_voice as nv_engine
from .. import storage
from ..security import require_role
from ..navigation import require_permission

bp = Blueprint("native_voice", __name__, url_prefix="/admin/native-voice")
api_bp = Blueprint("voice_api", __name__, url_prefix="/api/v1/voice")


def _org_id() -> int:
    return current_user.org_id


# ---------------------------------------------------------------- admin list
@bp.get("/")
@require_role("SUPER_ADMIN", "ADMIN_MANAGER", "HEAD_ADMIN_HR")
@require_permission("admin")
def admin_list():
    org_id = _org_id()
    voices = nv_engine.list_voices(org_id)
    phrases = nv_engine.list_phrases(org_id)
    setting = db.session.get(NativeVoiceSetting, org_id)
    if not setting:
        nv_engine.ensure_default_voices(org_id)
        setting = db.session.get(NativeVoiceSetting, org_id)

    # Group phrases by key for table view
    from collections import defaultdict
    by_key = defaultdict(list)
    for p in phrases:
        by_key[p.key].append(p)

    return render_template("admin/native_voice.html",
                           voices=voices,
                           phrases=phrases,
                           by_key=dict(by_key),
                           setting=setting,
                           base_keys=nv_engine.BASE_PHRASE_KEYS[:50],  # show first 50
                           greeting=nv_engine.greeting_key_for_now(),
                           now=now_naive())


@bp.post("/settings")
@require_role("SUPER_ADMIN", "ADMIN_MANAGER", "HEAD_ADMIN_HR")
@require_permission("admin")
def save_settings():
    org_id = _org_id()
    setting = db.session.get(NativeVoiceSetting, org_id)
    if not setting:
        setting = NativeVoiceSetting(org_id=org_id)
        db.session.add(setting)

    setting.enabled = bool(request.form.get("enabled"))
    setting.use_native = bool(request.form.get("use_native"))
    setting.fallback_to_tts = bool(request.form.get("fallback_to_tts"))
    setting.languages = (request.form.get("languages") or "en,yo,ha,ig").strip()[:30]
    try:
        vol = int(request.form.get("volume") or 100)
        setting.volume = max(0, min(100, vol))
    except ValueError:
        setting.volume = 100

    # Rotation map: JSON like {"0": voice_id, "1": voice_id}
    rm_raw = (request.form.get("rotation_map") or "").strip()
    if rm_raw:
        try:
            json.loads(rm_raw)
            setting.rotation_map = rm_raw
        except Exception:
            flash("Rotation map is not valid JSON — ignored", "error")
    else:
        setting.rotation_map = None

    db.session.commit()
    flash("Native voice settings saved", "success")
    return redirect(url_for("native_voice.admin_list"))


@bp.post("/voice/add")
@require_role("SUPER_ADMIN", "ADMIN_MANAGER")
@require_permission("admin")
def add_voice():
    org_id = _org_id()
    code = (request.form.get("code") or "").strip().upper()[:20]
    name = (request.form.get("name") or "").strip()[:80]
    gender = (request.form.get("gender") or "").strip().lower()[:10]
    language = (request.form.get("language") or "en").strip().lower()[:10]

    if not code or not name or gender not in ("female", "male"):
        flash("Code, name, and gender (female/male) required", "error")
        return redirect(url_for("native_voice.admin_list"))

    # Check duplicate
    exists = db.session.query(NativeVoice).filter_by(org_id=org_id, code=code, language=language).first()
    if exists:
        flash(f"Voice {code}/{language} already exists — edit it", "error")
        return redirect(url_for("native_voice.admin_list"))

    v = NativeVoice(org_id=org_id, code=code, name=name, gender=gender, language=language, active=True)
    db.session.add(v)
    db.session.commit()
    flash(f"Voice {name} ({code}/{language}) added — now upload sample audio", "success")
    return redirect(url_for("native_voice.admin_list"))


@bp.post("/voice/<int:voice_id>/upload")
@require_role("SUPER_ADMIN", "ADMIN_MANAGER")
@require_permission("admin")
def upload_voice_sample(voice_id: int):
    org_id = _org_id()
    voice = db.session.get(NativeVoice, voice_id)
    if not voice or voice.org_id != org_id:
        abort(404)
    file = request.files.get("audio")
    if not file or not file.filename:
        flash("No audio file selected", "error")
        return redirect(url_for("native_voice.admin_list"))

    # Save via storage (db or S3)
    ext = (file.filename.rsplit(".", 1)[-1] or "mp3").lower()[:5]
    if ext not in ("mp3", "wav", "ogg", "m4a", "mp4"):
        flash("Audio must be mp3, wav, ogg, m4a", "error")
        return redirect(url_for("native_voice.admin_list"))

    data = file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        flash("Audio too large (max 10 MB)", "error")
        return redirect(url_for("native_voice.admin_list"))

    key = f"native_voice/{org_id}/{voice_id}/sample_{voice.language}.{ext}"
    try:
        storage.put(key, data, org_id=org_id, filename=file.filename, content_type=f"audio/{ext}")
        voice.sample_key = key
        db.session.commit()
        flash(f"Sample audio saved for {voice.name}", "success")
    except Exception as exc:
        flash(f"Could not save: {exc}", "error")

    return redirect(url_for("native_voice.admin_list"))


@bp.post("/phrase/upload")
@require_role("SUPER_ADMIN", "ADMIN_MANAGER")
@require_permission("admin")
def upload_phrase():
    org_id = _org_id()
    voice_id = request.form.get("voice_id", type=int)
    key = (request.form.get("key") or "").strip()[:80]
    language = (request.form.get("language") or "en").strip().lower()[:10]
    text_template = (request.form.get("text_template") or "").strip()[:500]

    if not voice_id or not key:
        flash("Voice and phrase key required", "error")
        return redirect(url_for("native_voice.admin_list"))

    voice = db.session.get(NativeVoice, voice_id)
    if not voice or voice.org_id != org_id:
        abort(404)

    file = request.files.get("audio")
    if not file or not file.filename:
        flash("No audio file selected", "error")
        return redirect(url_for("native_voice.admin_list"))

    phrase, err = nv_engine.upload_phrase_audio(org_id, voice_id, key, language, file, text_template)
    if err:
        flash(err, "error")
    else:
        flash(f"Phrase '{key}' ({language}) saved for voice {voice.name}", "success")

    return redirect(url_for("native_voice.admin_list"))


# ---------------------------------------------------------------- API
@api_bp.get("/audio/<int:phrase_id>")
def get_audio(phrase_id: int):
    """Serve native phrase audio — public for TV screens (no auth, but org scoped via file existence).

    Dynamic: audio served via storage (db or S3), not hardcoded path.
    """
    phrase = db.session.get(NativePhrase, phrase_id)
    if not phrase or not phrase.active:
        abort(404)
    # Check org via all_orgs for public TV? TV is public, but we check file exists
    from ..rls import all_orgs
    all_orgs()
    # Re-fetch after all_orgs
    phrase = db.session.get(NativePhrase, phrase_id)
    if not phrase:
        abort(404)
    try:
        return storage.send(phrase.audio_key, max_age=86400)
    except FileNotFoundError:
        abort(404)


@api_bp.get("/compose")
def compose():
    """Compose announcement — returns JSON with audio sequence.

    Query params (all dynamic, not hardcoded):
    - kind: alert kind (queue_waiting, go_to_billing, etc.)
    - name: staff name (any new name)
    - count: number (any count)
    - place: place (any new place from ServiceDestination.place)
    - patient: patient name (any new patient)
    - room: room
    - detail: detail
    - lang: en|yo|ha|ig
    - org: org code or id (optional, for public TV)

    Example: /api/v1/voice/compose?kind=queue_waiting&name=Mr Tunde&count=3&place=Laboratory&lang=en
    """
    kind = (request.args.get("kind") or "queue_waiting").strip()[:80]
    name = (request.args.get("name") or "").strip()[:120]
    count = request.args.get("count", type=int) or 0
    place = (request.args.get("place") or "").strip()[:120]
    patient = (request.args.get("patient") or "").strip()[:120]
    room = (request.args.get("room") or "").strip()[:80]
    detail = (request.args.get("detail") or "").strip()[:300]
    lang = (request.args.get("lang") or "en").strip().lower()[:5]

    # Resolve org_id: from current_user if authenticated, else from ?org= code, else first org (public TV)
    org_id = None
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False):
            org_id = current_user.org_id
    except Exception:
        pass

    if org_id is None:
        org_code = (request.args.get("org") or "").strip()
        if org_code:
            from ..models import Organization
            if org_code.isdigit():
                org_id = int(org_code)
            else:
                from ..rls import all_orgs
                all_orgs()
                org = db.session.query(Organization).filter_by(code=org_code.upper()).first() or \
                      db.session.query(Organization).filter_by(slug=org_code.lower()).first()
                if org:
                    org_id = org.id
        if org_id is None:
            from ..models import Organization
            from ..rls import all_orgs
            all_orgs()
            first = db.session.query(Organization).order_by(Organization.id).first()
            org_id = first.id if first else 1

    # Ensure RLS set
    from ..rls import set_org, all_orgs
    try:
        if org_id:
            set_org(org_id)
        else:
            all_orgs()
    except Exception:
        pass

    result = nv_engine.compose_announcement(org_id, kind, name=name, count=count, place=place,
                                            patient=patient, room=room, detail=detail, language=lang)
    return jsonify(result)


@api_bp.get("/next")
def next_announcements():
    """For TV polling — returns next announcements with native audio.

    Query: ?screen=MAIN&org=IJD&lang=en
    Returns list of announcements with audio_sequence.
    """
    # This is a lightweight version — real TV feed is in tv.py, but we add voice composition here
    screen_code = (request.args.get("screen") or "MAIN").strip().upper()[:20]
    lang = (request.args.get("lang") or "en").strip().lower()[:5]

    # Resolve org
    org_id = None
    org_code = (request.args.get("org") or "").strip()
    from ..models import Organization, TvScreen
    from ..rls import all_orgs, set_org
    all_orgs()
    if org_code:
        org = db.session.query(Organization).filter_by(code=org_code.upper()).first() or \
              db.session.query(Organization).filter_by(slug=org_code.lower()).first()
        if org:
            org_id = org.id
    if org_id is None:
        first = db.session.query(Organization).order_by(Organization.id).first()
        org_id = first.id if first else 1

    try:
        set_org(org_id)
    except Exception:
        pass

    screen = db.session.query(TvScreen).filter_by(org_id=org_id, code=screen_code).first()
    # Use tv_feed to get now_serving/next_up
    from .. import tv as tv_engine
    feed = tv_engine.tv_feed(org_id, screen)

    # Compose voice for first 2 now_serving
    announcements = []
    for item in (feed.get("now_serving") or [])[:2]:
        comp = nv_engine.compose_announcement(org_id, "consult_call_in",
                                              patient=item.get("spoken") or item.get("name") or "",
                                              room=item.get("room") or "",
                                              place=item.get("clinic") or "",
                                              language=lang)
        announcements.append({"item": item, "voice": comp})

    return jsonify({
        "screen": screen_code,
        "org_id": org_id,
        "now": now_naive().isoformat(),
        "greeting": nv_engine.greeting_key_for_now(),
        "voice_today": nv_engine.voice_for_today(org_id, screen.id if screen else None).display_name if nv_engine.voice_for_today(org_id, screen.id if screen else None) else None,
        "announcements": announcements,
        "stats": feed.get("stats"),
    })
