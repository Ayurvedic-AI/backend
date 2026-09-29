"""Bhashini (ULCA) pipeline: free hosted AI4Bharat models. Register at bhashini.gov.in."""
import base64
from functools import lru_cache

import httpx

from app.asr.base import BackendError, Transcript
from app.audio import to_wav16k
from app.settings import settings

CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
PIPELINE_ID = "64392f96daac500b55c543cd"  # MeitY pipeline


@lru_cache
def pipeline_config(task: str, src: str, tgt: str | None = None) -> tuple[str, str, dict]:
    """-> (serviceId, callbackUrl, auth header) for one task/language."""
    lang = {"sourceLanguage": src} | ({"targetLanguage": tgt} if tgt else {})
    r = httpx.post(
        CONFIG_URL,
        headers={"userID": settings.bhashini_user_id, "ulcaApiKey": settings.bhashini_api_key},
        json={
            "pipelineTasks": [{"taskType": task, "config": {"language": lang}}],
            "pipelineRequestConfig": {"pipelineId": PIPELINE_ID},
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise BackendError(f"bhashini config {r.status_code}: {r.text[:200]}")
    j = r.json()
    ep = j["pipelineInferenceAPIEndPoint"]
    key = ep["inferenceApiKey"]
    return j["pipelineResponseConfig"][0]["config"][0]["serviceId"], ep["callbackUrl"], {key["name"]: key["value"]}


def infer(task: str, src: str, tgt: str | None, extra: dict, input_data: dict) -> dict:
    service_id, url, headers = pipeline_config(task, src, tgt)
    lang = {"sourceLanguage": src} | ({"targetLanguage": tgt} if tgt else {})
    r = httpx.post(
        url,
        headers=headers,
        json={
            "pipelineTasks": [{"taskType": task, "config": {"serviceId": service_id, "language": lang, **extra}}],
            "inputData": input_data,
        },
        timeout=60,
    )
    if r.status_code != 200:
        raise BackendError(f"bhashini {task} {r.status_code}: {r.text[:200]}")
    return r.json()["pipelineResponse"][0]["output"][0]


class BhashiniASR:
    def transcribe(self, path: str, lang: str) -> Transcript:
        wav = to_wav16k(path)
        audio = base64.b64encode(open(wav, "rb").read()).decode()
        out = infer("asr", lang, None, {"audioFormat": "wav", "samplingRate": 16000}, {"audio": [{"audioContent": audio}]})
        return Transcript(text=out["source"], model_name="bhashini-asr")
