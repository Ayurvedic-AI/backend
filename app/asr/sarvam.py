from sarvamai import SarvamAI

from app.asr.base import BackendError, Transcript
from app.settings import settings


MODEL = "saaras:v3"


class SarvamASR:
    def __init__(self):
        self.client = SarvamAI(api_subscription_key=settings.sarvam_api_key)

    def _call(self, path: str, lang: str, mode: str):
        with open(path, "rb") as f:
            return self.client.speech_to_text.transcribe(
                file=f, model=MODEL, mode=mode, language_code="unknown" if lang == "auto" else f"{lang}-IN"
            )

    def transcribe(self, path: str, lang: str) -> Transcript:
        # ponytail: 2 Sarvam calls/clip for hi/mr; collapse when billing matters
        try:
            r = self._call(path, lang, "transcribe")
            detected = (r.language_code or "")[:2] or None
            lang = detected or lang if lang == "auto" else lang
            english = self._call(path, lang, "translate").transcript if lang != "en" else None
        except Exception as e:
            raise BackendError(f"sarvam asr: {e}") from e
        return Transcript(text=r.transcript, model_name=MODEL, language=detected, english=english)
