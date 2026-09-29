import os
import wave

os.environ.update(DATABASE_URL="sqlite:///./test.db", STORAGE_DIR="./data/test_audio",
                  ASR_BACKEND="sarvam", MT_BACKEND="sarvam", SARVAM_API_KEY="x")

import pytest
from fastapi.testclient import TestClient

from app import chain
from app.asr.base import BackendError, Transcript
from app.main import app
from app.mt.base import Translation


class FakeASR:
    def __init__(self, english=None, fail=False, detected=None):
        self.english, self.fail, self.detected = english, fail, detected
    def transcribe(self, path, lang):
        if self.fail:
            raise BackendError("boom")
        return Transcript(text=f"raw-{lang}", model_name="fake-asr", english=self.english, language=self.detected)


class FakeMT:
    calls = 0
    def translate(self, text, src):
        FakeMT.calls += 1
        return Translation(text=f"en({text})", model_name="fake-mt")


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(chain, "ASR", FakeASR())
    monkeypatch.setattr(chain, "MT", FakeMT())
    FakeMT.calls = 0


def test_chain_skips_mt_for_english():
    out = chain.pipeline.invoke({"path": "x", "lang": "en"})
    assert out["translation"] is None and FakeMT.calls == 0


def test_chain_uses_asr_english_when_present(monkeypatch):
    monkeypatch.setattr(chain, "ASR", FakeASR(english="direct"))
    out = chain.pipeline.invoke({"path": "x", "lang": "hi"})
    assert out["translation"].text == "direct" and FakeMT.calls == 0


def test_chain_falls_back_to_mt():
    out = chain.pipeline.invoke({"path": "x", "lang": "mr"})
    assert out["translation"].text == "en(raw-mr)" and [r["stage"] for r in out["runs"]] == ["asr", "mt"]


def test_chain_auto_resolves_to_detected(monkeypatch):
    monkeypatch.setattr(chain, "ASR", FakeASR(detected="en"))
    out = chain.pipeline.invoke({"path": "x", "lang": "auto"})
    assert out["lang"] == "en" and out["translation"] is None and FakeMT.calls == 0


def _wav(tmp_path, seconds=1):
    p = tmp_path / "a.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\0\0" * 16000 * seconds)
    return p


def test_api_end_to_end(tmp_path, monkeypatch):
    c = TestClient(app)
    cid = c.post("/consultations").json()["id"]
    r = c.post(f"/consultations/{cid}/audio", files={"file": open(_wav(tmp_path), "rb")},
               data={"language": "hi", "speaker": "patient"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["raw_text"] == "raw-hi" and body["translated_text"] == "en(raw-hi)"

    r = c.put(f"/transcripts/{body['transcript_id']}",
              json={"edited_text": "fixed", "edited_by": "dr", "translation_id": body["translation_id"]})
    assert r.status_code == 200
    rows = c.get(f"/consultations/{cid}/transcripts").json()
    assert rows[0]["edited_translation"] == "fixed" and rows[0]["edited_text"] is None

    assert c.post(f"/consultations/{cid}/audio", files={"file": open(_wav(tmp_path, 31), "rb")},
                  data={"language": "hi"}).status_code == 413

    monkeypatch.setattr(chain, "ASR", FakeASR(fail=True))
    r = c.post(f"/consultations/{cid}/audio", files={"file": open(_wav(tmp_path), "rb")}, data={"language": "hi"})
    assert r.status_code == 502 and "boom" in r.json()["detail"]
