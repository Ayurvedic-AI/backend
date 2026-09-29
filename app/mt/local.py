"""IndicTrans2 on CPU. Needs requirements-local.txt."""
from functools import lru_cache

from app.mt.base import Translation

MODEL = "ai4bharat/indictrans2-indic-en-dist-200M"
TAG = {"hi": "hin_Deva", "mr": "mar_Deva"}


@lru_cache
def _load():
    from IndicTransToolkit.processor import IndicProcessor
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL, trust_remote_code=True)
    return IndicProcessor(inference=True), tok, model


class LocalMT:
    def translate(self, text: str, src: str) -> Translation:
        import torch

        ip, tok, model = _load()
        batch = ip.preprocess_batch([text], src_lang=TAG[src], tgt_lang="eng_Latn")
        inputs = tok(batch, padding="longest", truncation=True, max_length=256, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**inputs, max_length=256, num_beams=5)
        decoded = tok.batch_decode(out, skip_special_tokens=True)
        return Translation(text=ip.postprocess_batch(decoded, lang="eng_Latn")[0], model_name=MODEL)
