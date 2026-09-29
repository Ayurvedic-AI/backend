from sarvamai import SarvamAI

from app.asr.base import BackendError
from app.mt.base import Translation
from app.settings import settings

MODEL = "mayura:v1"


class SarvamMT:
    def __init__(self):
        self.client = SarvamAI(api_subscription_key=settings.sarvam_api_key)

    def translate(self, text: str, src: str) -> Translation:
        try:
            r = self.client.text.translate(
                input=text, source_language_code=f"{src}-IN", target_language_code="en-IN", model=MODEL
            )
        except Exception as e:
            raise BackendError(f"sarvam mt: {e}") from e
        return Translation(text=r.translated_text, model_name=MODEL)
