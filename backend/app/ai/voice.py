"""Speech to text with Meta's Muse Voice Transcribe (POST /v1/asr/transcribe).

The endpoint takes WAV only: mono, 16-bit PCM at 16 or 24 kHz. Audio is checked here before it is sent, and it is
never stored.
"""

import io
import json
import logging
import time
import uuid
import wave

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ModelCall

MODEL_ID = "muse-voice-transcribe-1.0"
MAX_SECONDS = 120
MAX_BYTES = 24000 * 2 * MAX_SECONDS + 1024
RATES = (16000, 24000)

log = logging.getLogger("ai")


class VoiceError(Exception):
    pass


def check_wav(data: bytes) -> str | None:
    """Return why the audio can't be sent, or None if it's a supported WAV."""
    if len(data) > MAX_BYTES:
        return f"Recordings can be up to {MAX_SECONDS // 60} minutes long"
    try:
        with wave.open(io.BytesIO(data)) as w:
            channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    except (wave.Error, EOFError):
        return "The recording must be a WAV file"
    if channels != 1 or width != 2 or rate not in RATES:
        return "The recording must be mono 16-bit WAV at 16 or 24 kHz"
    if frames / rate > MAX_SECONDS:
        return f"Recordings can be up to {MAX_SECONDS // 60} minutes long"
    return None


def _post(audio: bytes) -> dict:
    s = get_settings()
    request = {"model": MODEL_ID, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    try:
        r = httpx.post(
            f"{s.meta_base_url}/asr/transcribe",
            headers={"Authorization": f"Bearer {s.model_api_key}", "Accept": "application/json"},
            files={"request": (None, json.dumps(request), "application/json"), "audio": ("voice.wav", audio, "audio/wav")},
            timeout=s.ai_timeout_seconds,
        )
    except httpx.HTTPError as e:
        raise VoiceError(type(e).__name__) from e
    if r.status_code != 200:
        raise VoiceError(f"HTTP {r.status_code}")
    return r.json()


def transcribe(db: Session, audio: bytes, org_id: uuid.UUID) -> str:
    """Send a checked WAV to Meta and return the transcript. Every call is logged without its content."""
    started = time.monotonic()
    call = ModelCall(org_id=org_id, task="voice_transcribe", provider="meta", model_id=MODEL_ID, status="ok", latency_ms=0)
    try:
        out = _post(audio)
        call.response_id = str(out.get("sessionId") or "")[:100] or None
        return str(out.get("transcript") or "").strip()
    except VoiceError as e:
        call.status, call.error = "error", str(e)[:500]
        raise
    finally:
        call.latency_ms = (time.monotonic() - started) * 1000
        db.add(call)
        db.flush()
        log.info("meta inference task=voice_transcribe model=%s status=%s latency_ms=%.0f", MODEL_ID, call.status, call.latency_ms)
