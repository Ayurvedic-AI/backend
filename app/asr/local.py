"""Offline CPU fallback. Needs requirements-local.txt (torch etc.)."""
from functools import lru_cache

from app.asr.base import Transcript
from app.audio import to_wav16k

CONFORMER = "ai4bharat/indic-conformer-600m-multilingual"
WHISPER = "small"  # bump when a GPU exists


@lru_cache
def _conformer():
    from transformers import AutoModel

    return AutoModel.from_pretrained(CONFORMER, trust_remote_code=True)


@lru_cache
def _whisper():
    from faster_whisper import WhisperModel

    return WhisperModel(WHISPER, device="cpu", compute_type="int8")


class LocalASR:
    def transcribe(self, path: str, lang: str) -> Transcript:
        wav = to_wav16k(path)
        if lang == "en":
            segments, _ = _whisper().transcribe(wav, language="en")
            return Transcript(text=" ".join(s.text.strip() for s in segments), model_name=f"whisper-{WHISPER}")
        import torchaudio

        audio, _ = torchaudio.load(wav)
        text = _conformer()(audio, lang, "ctc")
        return Transcript(text=text, model_name=CONFORMER)
