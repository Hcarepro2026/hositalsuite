"""Native Voice Phrase Bank — phrase, not clone, dynamic time/name aware.

WHY THIS EXISTS
---------------
Chrome/Google TTS (speechSynthesis) sounds foreign. Founder rule: native recorded
phrase bank waits for pick, phrase bank not clone. This module implements it.

DYNAMIC DESIGN (be mindful of changes of time, changes of names)
------------------------------------------------------------------
- Time changes: greeting_morning (5-11), greeting_afternoon (12-16), greeting_evening (17-23),
  plus day_of_week, date — all via now_naive() with TIMEZONE Africa/Lagos, not hardcoded.
- Name changes: {name} placeholder via speech_name() from announce.py — title + first name,
  not full name, not hardcoded. Works for any new staff/patient name.
- Count changes: number_1...number_100 recordings + fallback to TTS number. Plural handled.
- Place changes: place_laboratory, place_pharmacy, place_billing, place_triage, etc. per language,
  plus custom places from ServiceDestination.place field (dynamic, per-tenant).
- Language changes: en, yo, ha, ig — 4 Nigerian languages, per-tenant setting.
- Voice rotation: 2 male 2 female recycled daily (FEMALE1, MALE1, FEMALE2, MALE2) via day_of_year %4,
  per org, dynamic — not hardcoded to one voice.

PHRASE BANK, NOT CLONE
----------------------
- Each phrase is a real human recording (mp3/wav) uploaded by admin, stored via storage.py (db or S3).
- No AI voice cloning, no model training. Just concatenation of recorded segments.
- If native audio missing for a key, fallback to TTS phrase() from announce.py if fallback_to_tts enabled.

USAGE
-----
- Admin → Native Voice → upload sample for each voice (Ada, Emeka, Folake, Chinedu) + phrases
- TV / station screens poll /api/v1/voice/next?screen=MAIN → gets audio URLs to play sequentially
- Frontend plays via <audio> elements, not speechSynthesis — sounds native.

"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from flask import current_app

from .models import NativePhrase, NativeVoice, NativeVoiceSetting, Organization, TvScreen, db, now_naive
from . import storage
from .announce import speech_name, plural


# ------------------------------------------------------------------ defaults
DEFAULT_VOICES = [
    {"code": "FEMALE1", "name": "Ada", "gender": "female", "language": "en"},
    {"code": "MALE1", "name": "Emeka", "gender": "male", "language": "en"},
    {"code": "FEMALE2", "name": "Folake", "gender": "female", "language": "en"},
    {"code": "MALE2", "name": "Chinedu", "gender": "male", "language": "en"},
    # Yoruba voices
    {"code": "FEMALE1", "name": "Ada", "gender": "female", "language": "yo"},
    {"code": "MALE1", "name": "Emeka", "gender": "male", "language": "yo"},
    # Hausa
    {"code": "FEMALE1", "name": "Aisha", "gender": "female", "language": "ha"},
    {"code": "MALE1", "name": "Musa", "gender": "male", "language": "ha"},
    # Igbo
    {"code": "FEMALE1", "name": "Ngozi", "gender": "female", "language": "ig"},
    {"code": "MALE1", "name": "Obinna", "gender": "male", "language": "ig"},
]

# Base phrase keys that should exist per language (seed list, dynamic)
BASE_PHRASE_KEYS = [
    # Greetings by time (dynamic)
    "greeting_morning", "greeting_afternoon", "greeting_evening", "greeting_general",
    # Core alerts (from announce.py PATIENT_ALERTS)
    "queue_waiting", "queue_assigned", "dispensary_waiting", "triage_backlog",
    "consult_ready", "lab_waiting", "emergency_arrival", "patient_waiting_long",
    "reception_waiting", "patient_registered", "assistance_needed", "returning_patient",
    "reception_arrival", "go_to_billing", "go_to_payment", "ready_for_folder",
    "go_to_triage", "consult_call_in", "go_onward", "desk_expecting", "visit_complete",
    "flow_bottleneck", "patient_forgotten", "colleague_joined", "dept_falling_behind",
    "complaint_for_you", "complaint_running_out", "complaint_escalated",
    "complaint_sla_warning_voice", "complaint_escalated_voice",
    # Numbers 0-20, then tens (dynamic count)
    *[f"number_{i}" for i in range(0, 21)],
    "number_30", "number_40", "number_50", "number_100", "number_many",
    # Places (dynamic, per-tenant but seed common)
    "place_laboratory", "place_pharmacy", "place_billing", "place_payment",
    "place_triage", "place_reception", "place_hims", "place_dental", "place_opd",
    "place_emergency", "place_ward", "place_theater",
    # Connectors (for stitching)
    "connector_please", "connector_go_to", "connector_waiting_at", "connector_and",
    "connector_is", "connector_are",
    # Time words
    "time_today", "time_tomorrow", "time_morning", "time_afternoon", "time_evening",
]

# Time-based greeting logic (dynamic, not hardcoded string)
def greeting_key_for_now() -> str:
    h = now_naive().hour
    if 5 <= h < 12:
        return "greeting_morning"
    if 12 <= h < 17:
        return "greeting_afternoon"
    if 17 <= h < 24:
        return "greeting_evening"
    return "greeting_general"


def ensure_default_voices(org_id: int) -> list[NativeVoice]:
    """Seed 4 default voices per org if none exist. Idempotent, dynamic per org."""
    existing = db.session.query(NativeVoice).filter_by(org_id=org_id).all()
    if existing:
        return existing
    created = []
    for v in DEFAULT_VOICES:
        # Only seed en voices by default to keep it light; other langs on demand
        if v["language"] != "en" and v["code"] not in ("FEMALE1", "MALE1"):
            continue
        row = NativeVoice(
            org_id=org_id,
            code=v["code"],
            name=v["name"],
            gender=v["gender"],
            language=v["language"],
            active=True,
            is_default=True,
        )
        db.session.add(row)
        created.append(row)
    db.session.flush()
    # Ensure setting exists
    setting = db.session.get(NativeVoiceSetting, org_id)
    if not setting:
        setting = NativeVoiceSetting(org_id=org_id, enabled=False, use_native=True, fallback_to_tts=True, languages="en,yo,ha,ig", volume=100)
        db.session.add(setting)
    db.session.commit()
    return db.session.query(NativeVoice).filter_by(org_id=org_id).all()


def voice_for_today(org_id: int, screen_id: int | None = None) -> NativeVoice | None:
    """Pick voice for today via daily rotation, dynamic.

    Rotation: day_of_year % 4 → FEMALE1, MALE1, FEMALE2, MALE2
    If org has custom rotation_map in setting, use it.
    """
    ensure_default_voices(org_id)
    day = now_naive().timetuple().tm_yday
    slot = day % 4
    slot_codes = ["FEMALE1", "MALE1", "FEMALE2", "MALE2"]

    setting = db.session.get(NativeVoiceSetting, org_id)
    # Check custom rotation map
    if setting and setting.rotation_map:
        try:
            rm = json.loads(setting.rotation_map)
            # rm like {"0": 5, "1": 6, ...} mapping slot->voice_id
            vid = rm.get(str(slot))
            if vid:
                v = db.session.get(NativeVoice, int(vid))
                if v and v.org_id == org_id and v.active:
                    return v
        except Exception:
            pass

    # Default: pick by code + language en
    code = slot_codes[slot]
    v = (db.session.query(NativeVoice)
         .filter_by(org_id=org_id, code=code, language="en", active=True)
         .first())
    if v:
        return v
    # Fallback: any active voice
    return (db.session.query(NativeVoice)
            .filter_by(org_id=org_id, active=True)
            .order_by(NativeVoice.id)
            .first())


def get_phrase_audio(org_id: int, key: str, language: str = "en", voice_id: int | None = None) -> dict[str, Any] | None:
    """Get native phrase audio if exists, else None (fallback to TTS)."""
    q = db.session.query(NativePhrase).filter_by(org_id=org_id, key=key, language=language, active=True)
    if voice_id:
        q = q.filter_by(voice_id=voice_id)
    row = q.order_by(NativePhrase.id).first()
    if row and row.audio_key and storage.exists(row.audio_key):
        return {
            "key": row.key,
            "language": row.language,
            "text": row.text_template,
            "audio_url": f"/api/v1/voice/audio/{row.id}",
            "audio_key": row.audio_key,
            "voice_id": row.voice_id,
            "duration_ms": row.duration_ms,
        }
    return None


def compose_announcement(org_id: int, kind: str, *, name: str = "", count: int = 0,
                         place: str = "", patient: str = "", room: str = "",
                         detail: str = "", language: str = "en") -> dict[str, Any]:
    """Compose dynamic announcement using phrase bank + dynamic inserts.

    Returns dict with:
    - text: final spoken text (with dynamic name/count/place)
    - audio_sequence: list of audio URLs to play in order (native) or empty if TTS
    - use_native: bool
    - fallback_text: TTS text if native missing

    Dynamic handling:
    - Time: greeting based on now_naive().hour
    - Name: speech_name() shortens any new name, not hardcoded
    - Count: number_{n} recordings or TTS plural
    - Place: place_* recordings per language, or dynamic ServiceDestination.place
    """
    from .announce import phrase as tts_phrase

    setting = db.session.get(NativeVoiceSetting, org_id)
    if not setting:
        ensure_default_voices(org_id)
        setting = db.session.get(NativeVoiceSetting, org_id)

    use_native = bool(setting and setting.enabled and setting.use_native)
    fallback = bool(setting and setting.fallback_to_tts)

    voice = voice_for_today(org_id)
    voice_id = voice.id if voice else None

    # Build TTS fallback text always (dynamic)
    tts_text = tts_phrase(kind, name=name, count=count, place=place, patient=patient, room=room, detail=detail)

    if not use_native:
        return {
            "text": tts_text,
            "audio_sequence": [],
            "use_native": False,
            "fallback_text": tts_text,
            "voice": voice.display_name if voice else None,
            "language": language,
            "greeting": greeting_key_for_now(),
        }

    # Try to get native audio for this kind
    native = get_phrase_audio(org_id, kind, language=language, voice_id=voice_id)
    if native:
        # For dynamic parts, try to stitch additional audios
        sequence = [native]
        # If count dynamic, add number audio
        if count:
            num_key = f"number_{count}" if count <= 20 else ("number_many" if count > 100 else None)
            if num_key:
                num_audio = get_phrase_audio(org_id, num_key, language=language, voice_id=voice_id)
                if num_audio:
                    sequence.append(num_audio)
        # If place dynamic, add place audio
        if place:
            # Normalize place to key: "the Laboratory" -> place_laboratory
            place_key = "place_" + "".join(c for c in place.lower() if c.isalnum() or c == "_").replace("the_", "").replace(" ", "_")[:30]
            # Try exact, then fallback to generic
            p_audio = get_phrase_audio(org_id, place_key, language=language, voice_id=voice_id)
            if not p_audio:
                # Try common places
                for common in ["place_laboratory", "place_pharmacy", "place_billing", "place_triage", "place_reception"]:
                    if common.split("_")[1] in place.lower():
                        p_audio = get_phrase_audio(org_id, common, language=language, voice_id=voice_id)
                        if p_audio:
                            break
            if p_audio:
                sequence.append(p_audio)

        return {
            "text": native["text"] or tts_text,
            "audio_sequence": sequence,
            "use_native": True,
            "fallback_text": tts_text,
            "voice": voice.display_name if voice else None,
            "language": language,
            "greeting": greeting_key_for_now(),
            "dynamic": {
                "name": speech_name(name) if name else "",
                "patient": speech_name(patient) if patient else "",
                "count": count,
                "place": place,
                "room": room,
                "time_greeting": greeting_key_for_now(),
                "now_hour": now_naive().hour,
                "now_date": now_naive().date().isoformat(),
            }
        }

    # No native for this kind — fallback to TTS if allowed
    if fallback:
        return {
            "text": tts_text,
            "audio_sequence": [],
            "use_native": False,
            "fallback_text": tts_text,
            "voice": voice.display_name if voice else None,
            "language": language,
            "greeting": greeting_key_for_now(),
        }

    # No audio and no fallback — return text only
    return {
        "text": tts_text,
        "audio_sequence": [],
        "use_native": False,
        "fallback_text": None,
        "voice": None,
        "language": language,
    }


def list_voices(org_id: int) -> list[NativeVoice]:
    ensure_default_voices(org_id)
    return db.session.query(NativeVoice).filter_by(org_id=org_id, active=True).order_by(NativeVoice.language, NativeVoice.code).all()


def list_phrases(org_id: int, language: str | None = None) -> list[NativePhrase]:
    q = db.session.query(NativePhrase).filter_by(org_id=org_id, active=True)
    if language:
        q = q.filter_by(language=language)
    return q.order_by(NativePhrase.key).all()


def upload_phrase_audio(org_id: int, voice_id: int, key: str, language: str, file_storage, text_template: str = "") -> tuple[NativePhrase | None, str | None]:
    """Upload audio for a phrase. Returns (phrase, error). Dynamic file handling."""
    from .security import validate_upload
    from .models import now_naive

    safe, err = validate_upload(file_storage)
    if err:
        # Allow mp3/wav — validate_upload only allows jpg/png/webp/pdf, so check manually for audio
        ext = (file_storage.filename or "").lower().rsplit(".", 1)[-1]
        if ext not in ("mp3", "wav", "ogg", "m4a", "mp4"):
            return None, f"Audio must be mp3, wav, ogg, m4a — got {ext}. {err}"
        # For audio, bypass image validation, just check size
        file_storage.seek(0)
        data = file_storage.read(10 * 1024 * 1024 + 1)  # 10 MB max for audio
        if len(data) > 10 * 1024 * 1024:
            return None, "Audio too large (max 10 MB)"
        safe = f"native_voice/{org_id}/{voice_id}/{key}_{language}.{ext}"
    else:
        # Was validated as image/pdf but we want audio — still allow if audio ext
        ext = (file_storage.filename or "").lower().rsplit(".", 1)[-1]
        if ext not in ("mp3", "wav", "ogg", "m4a", "mp4", "pdf", "jpg", "png"):
            # Actually safe from validate_upload is image — but we need audio, so recreate key
            pass

    file_storage.seek(0)
    data = file_storage.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        return None, "Audio too large (max 10 MB)"

    # Use storage.py (db or S3)
    audio_key = f"native_voice/{org_id}/{voice_id}/{key}_{language}_{int(datetime.now().timestamp())}.{ext if 'ext' in locals() else 'mp3'}"
    try:
        storage.put(audio_key, data, org_id=org_id, filename=file_storage.filename, content_type=f"audio/{ext if 'ext' in locals() else 'mp3'}")
    except Exception as exc:
        return None, f"Could not save audio: {exc}"

    # Upsert phrase
    phrase = (db.session.query(NativePhrase)
              .filter_by(org_id=org_id, voice_id=voice_id, key=key, language=language)
              .first())
    if not phrase:
        phrase = NativePhrase(org_id=org_id, voice_id=voice_id, key=key, language=language,
                              text_template=text_template[:500] if text_template else key,
                              audio_key=audio_key, active=True)
        db.session.add(phrase)
    else:
        phrase.audio_key = audio_key
        if text_template:
            phrase.text_template = text_template[:500]
        phrase.updated_at = now_naive()
    db.session.commit()
    return phrase, None
