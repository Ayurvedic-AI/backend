"""ASR -> (maybe) translate, as a LangChain RunnableSequence.
# ponytail: 2-step RunnableSequence; add prompt/LLM nodes when the reply feature lands.
"""
import time
from importlib import import_module

from langchain_core.runnables import RunnableLambda

from app.asr.base import BackendError
from app.mt.base import Translation
from app.settings import settings


def _backend(kind: str, name: str):
    return getattr(import_module(f"app.{kind}.{name}"), f"{name.capitalize()}{kind.upper()}")()


ASR = _backend("asr", settings.asr_backend)
MT = _backend("mt", settings.mt_backend)


def _timed(inp: dict, stage: str, backend: str, fn):
    t0 = time.perf_counter()
    try:
        result = fn()
        status, error = "ok", None
    except BackendError as e:
        result, status, error = None, "error", str(e)
    inp.setdefault("runs", []).append({
        "stage": stage, "backend": backend, "model_name": getattr(result, "model_name", "-"),
        "duration_ms": int((time.perf_counter() - t0) * 1000), "status": status, "error": error,
    })
    if error:
        raise BackendError(error)
    return result


def _asr(inp: dict) -> dict:
    inp["transcript"] = _timed(inp, "asr", settings.asr_backend, lambda: ASR.transcribe(inp["path"], inp["lang"]))
    return inp


def _mt(inp: dict) -> dict:
    t = inp["transcript"]
    lang = inp["lang"] = t.language or inp["lang"]   # resolve "auto" to what the model detected
    if lang == "en":
        inp["translation"] = None
    elif t.english:
        inp["translation"] = Translation(text=t.english, model_name=t.model_name)
    else:
        inp["translation"] = _timed(inp, "mt", settings.mt_backend, lambda: MT.translate(t.text, lang))
    return inp


pipeline = RunnableLambda(_asr) | RunnableLambda(_mt)
