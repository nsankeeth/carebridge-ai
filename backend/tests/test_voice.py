import io
import wave

import pytest
from sqlalchemy import select

from app.ai import voice
from app.db import SessionLocal
from app.models import AuditEvent, ModelCall


def wav_bytes(*, rate: int = 16000, channels: int = 1, width: int = 2, seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(rate * seconds) * channels * width)
    return buf.getvalue()


@pytest.fixture
def meta_asr(monkeypatch):
    """Stand-in for Meta's /v1/asr/transcribe; records what was sent."""
    sent: list[bytes] = []

    def fake(audio: bytes) -> dict:
        sent.append(audio)
        return {"transcript": "My daughter has been vomiting since this morning.", "audioDurationMs": 1000, "sessionId": "s1"}

    monkeypatch.setattr(voice, "_post", fake)
    return sent


def _send(client, headers, data: bytes, name: str = "voice.wav", content_type: str = "audio/wav"):
    return client.post("/api/patient/transcribe", headers=headers, files={"audio": (name, data, content_type)})


def test_patient_voice_is_transcribed_by_meta_and_logged(client, auth, meta_asr):
    r = _send(client, auth["patient_a"], wav_bytes())
    assert r.status_code == 200, r.text
    assert r.json() == {"transcript": "My daughter has been vomiting since this morning."}
    assert len(meta_asr) == 1
    db = SessionLocal()
    call = db.scalars(select(ModelCall).where(ModelCall.task == "voice_transcribe")).one()
    assert call.model_id == "muse-voice-transcribe-1.0" and call.status == "ok"
    event = db.scalars(select(AuditEvent).where(AuditEvent.action == "voice.transcribed")).one()
    assert "transcript" not in event.details and "vomiting" not in str(event.details), "no medical content in the audit log"
    db.close()


@pytest.mark.parametrize(
    "data",
    [
        b"not audio at all",
        wav_bytes(channels=2),
        wav_bytes(rate=44100),
        wav_bytes(width=1),
        wav_bytes(seconds=voice.MAX_SECONDS + 1),
    ],
    ids=["not-wav", "stereo", "44khz", "8bit", "too-long"],
)
def test_unsupported_audio_is_rejected_before_calling_meta(client, auth, meta_asr, data):
    r = _send(client, auth["patient_a"], data)
    assert r.status_code == 400
    assert meta_asr == []


def test_only_patients_can_transcribe(client, auth, meta_asr):
    assert _send(client, auth["clin_a"], wav_bytes()).status_code == 403
    assert client.post("/api/patient/transcribe", files={"audio": ("v.wav", wav_bytes(), "audio/wav")}).status_code == 401
    assert meta_asr == []


def test_meta_failure_returns_a_clear_error_and_is_logged(client, auth, monkeypatch):
    def boom(audio: bytes) -> dict:
        raise voice.VoiceError("upstream 500")

    monkeypatch.setattr(voice, "_post", boom)
    r = _send(client, auth["patient_a"], wav_bytes())
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "transcription_failed"
    call = SessionLocal().scalars(select(ModelCall).where(ModelCall.task == "voice_transcribe")).one()
    assert call.status == "error"


def test_empty_transcript_is_reported(client, auth, monkeypatch):
    monkeypatch.setattr(voice, "_post", lambda audio: {"transcript": "  ", "audioDurationMs": 1000})
    r = _send(client, auth["patient_a"], wav_bytes())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "no_speech"
