from app.asr.bhashini import infer
from app.mt.base import Translation


class BhashiniMT:
    def translate(self, text: str, src: str) -> Translation:
        out = infer("translation", src, "en", {}, {"input": [{"source": text}]})
        return Translation(text=out["target"], model_name="bhashini-indictrans2")
