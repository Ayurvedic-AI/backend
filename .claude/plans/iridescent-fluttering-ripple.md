# Speech-only MVP: Hindi/Marathi ASR → English transcript

## Context

Greenfield project (folder is empty, no GPU, Python 3.14 on the box). Goal: a doctor-consultation
transcription service. Audio in Hindi/Marathi/English → original transcript → English translation →
stored for doctor review/edit. LLM reply, TTS and the Ayurvedic RAG are explicitly out of scope for now.

User decisions: FastAPI + LangChain (for later scale), **Sarvam AI as primary backend** (user has an API key;
best accuracy, stays useful in production), Bhashini as free secondary, local CPU as offline fallback.
SQLite + local disk now with Postgres/S3 switchable by env.

Verified facts that shape the plan:
- IndicWhisper has **no hosted API**. It is MIT Whisper-medium checkpoints, one per language
  (AI4Bharat/vistaar repo). Self-host or don't use it.
- **Bhashini** gives free dev API keys (userID + ulcaApiKey) and hosts AI4Bharat ASR (IndicConformer),
  IndicTrans2 translation and TTS. Low-volume free; production needs a paid discussion.
- **HF ZeroGPU** free tier is ~3.5–5 GPU-minutes/day and every API call burns it → demo only, not a dev API.
- Local CPU: `ai4bharat/indic-conformer-600m-multilingual` loads via `transformers` `trust_remote_code`
  (no NeMo), and `ai4bharat/indictrans2-indic-en-dist-200M` runs fine on CPU for short text.
- **Sarvam AI**: single `POST /speech-to-text` endpoint, model `saaras:v3`. `mode=transcribe` returns the
  native-script transcript, `mode=translate` returns English directly from speech (better than text MT).
  Language codes `hi-IN`, `mr-IN`, `en-IN`. The old `/speech-to-text-translate` endpoint and `saarika:v2.5`
  are legacy; do not use them. Python SDK: `sarvamai`.

## Architecture

```
POST /consultations                       -> create consultation id
POST /consultations/{id}/audio            -> multipart upload (wav/mp3/webm), language, speaker
        | save file (storage backend)
        | ffmpeg -> 16 kHz mono wav
        | ASR backend  (sarvam | bhashini | local)      --+ LangChain RunnableSequence
        | translate backend (sarvam | bhashini | local) --+ (skip when language == en, or when
        |                                                    the ASR backend already returned English)
        | persist transcript + translation + model_run
GET  /consultations/{id}/transcripts      -> original + english, with edits
PUT  /transcripts/{id}                    -> doctor edit (stores doctor_edits row, never overwrites raw)
```

Backends selected by env: `ASR_BACKEND=sarvam|bhashini|local` (default `sarvam`),
`MT_BACKEND=sarvam|bhashini|local`, `STORAGE=local|s3`, `DATABASE_URL=sqlite:///./mvp.db`
(later `postgresql://...`).

## Files (keep it to these)

```
app/
  main.py          FastAPI app + routes
  settings.py      pydantic-settings; env vars above + SARVAM_API_KEY, BHASHINI_USER_ID, BHASHINI_API_KEY
  db.py            SQLAlchemy engine/session + models (6 tables below)
  storage.py       save_audio(bytes, name) -> url  (local disk; S3 branch via boto3 when STORAGE=s3)
  audio.py         to_wav16k(path) -> path  (subprocess ffmpeg)
  asr/
    base.py        Protocol: transcribe(wav_path, lang) -> Transcript(text, confidence|None, model_name, english|None)
    sarvam.py      saaras:v3 transcribe (+ translate mode for hi/mr, fills `english`)
    bhashini.py    ULCA pipeline call
    local.py       IndicConformer (hi/mr) + faster-whisper (en)
  mt/
    base.py        Protocol: translate(text, src) -> Translation(text, model_name)
    sarvam.py      POST /translate (mayura), used only when ASR backend did not return `english`
    bhashini.py
    local.py       IndicTrans2 dist-200M via transformers + IndicTransToolkit
  chain.py         LangChain: RunnableLambda(asr) | RunnableLambda(maybe_translate)
requirements.txt
.env.example
README.md          setup + curl examples
```

LangChain usage is deliberately thin: the two steps are `RunnableLambda`s composed with `|`. This gives
the hook for later LLM/RAG steps without any agent/prompt machinery today.
`# ponytail: LangChain is a 2-step RunnableSequence; add prompts/LLM nodes when the reply feature lands.`

## Sarvam integration (asr/sarvam.py, mt/sarvam.py) — primary

- `sarvamai` SDK, `SarvamAI(api_subscription_key=settings.sarvam_api_key)`.
- ASR: `client.speech_to_text.transcribe(file=open(wav,"rb"), model="saaras:v3", mode="transcribe",
  language_code="hi-IN"|"mr-IN"|"en-IN")` → `Transcript.text`. For hi/mr, a second call with
  `mode="translate"` fills `Transcript.english` (speech→English is more accurate than text MT).
  Two calls per clip is accepted for the MVP; `# ponytail: 2 Sarvam calls/clip, collapse when billing matters`.
- MT: `client.text.translate(input=text, source_language_code="hi-IN", target_language_code="en-IN",
  model="mayura:v1")`. Only reached when `english` is empty (i.e. bhashini/local ASR was used with MT=sarvam).
- Errors: wrap SDK exceptions in `BackendError` → 502. Sarvam limits uploads to ~30 s per REST call;
  reject longer clips with 413 and a message, chunking is a later step.

## Bhashini integration (asr/bhashini.py, mt/bhashini.py) — free secondary

1. Register at https://bhashini.gov.in (ULCA) → userID + ulcaApiKey → `.env`.
2. On first use, POST `https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline`
   with headers `userID`, `ulcaApiKey`, body `pipelineId: "64392f96daac500b55c543cd"` (MeitY pipeline)
   and tasks `[asr, translation]` for the language. Response gives `serviceId`s, the inference
   `callbackUrl`, and an `Authorization` header value. Cache in-process (`functools.lru_cache` keyed by lang).
3. Inference: POST `callbackUrl` (`https://dhruva-api.bhashini.gov.in/services/inference/pipeline`)
   with base64 wav, `sourceLanguage`, `targetLanguage: en`. One request can run ASR+translation together;
   we still expose them as two backends so local/bhashini can be mixed.
4. Use `httpx` with a 60 s timeout; raise a clear `BackendError` on non-200 so the route returns 502.

## Local fallback (asr/local.py, mt/local.py)

- hi/mr ASR: `AutoModel.from_pretrained("ai4bharat/indic-conformer-600m-multilingual", trust_remote_code=True)`,
  `torchaudio.load` → 16 kHz mono → `model(wav, lang, "ctc")`. Load once at module level (lazy on first call).
- en ASR: `faster_whisper.WhisperModel("small", compute_type="int8")` on CPU. (large-v3 is too slow without GPU;
  bump via env `WHISPER_SIZE` when a GPU exists.)
- Translation: `ai4bharat/indictrans2-indic-en-dist-200M` + `IndicTransToolkit` `IndicProcessor` for
  pre/post-processing. Language tags: hi → `hin_Deva`, mr → `mar_Deva`, en → `eng_Latn`.
- IndicWhisper (optional, not default): document in README how to point `faster-whisper` at a
  CT2-converted vistaar checkpoint; not wired by default since IndicConformer covers both languages in one model.

## Database (db.py)

Tables (from the user's plan, minus `language_detections` since language is chosen explicitly):

- `consultations(id, created_at, notes)`
- `audio_files(id, consultation_id, speaker, language, file_url, duration_seconds, sample_rate, uploaded_at)`
- `transcripts(id, audio_file_id, model_name, language, raw_text, confidence, start_time, end_time)`
- `translations(id, transcript_id, source_language, target_language, translated_text, model_name)`
- `doctor_edits(id, transcript_id, translation_id NULLABLE, original_text, edited_text, edited_by, edited_at)`
- `model_runs(id, audio_file_id, stage, backend, model_name, duration_ms, status, error)`

Raw ASR text and raw translation are never overwritten; edits append to `doctor_edits`.
`GET transcripts` returns raw + latest edit. `Base.metadata.create_all` at startup; no Alembic until
the schema changes for real.

## Environment

- Use a Python 3.12 venv (`uv venv -p 3.12 && uv pip install -r requirements.txt`). Torch on 3.14 is risky.
- `requirements.txt`: fastapi, uvicorn[standard], python-multipart, pydantic-settings, sqlalchemy, httpx,
  sarvamai, langchain-core, boto3 (s3 branch). Local-model deps (torch, torchaudio, transformers,
  faster-whisper, IndicTransToolkit) go in `requirements-local.txt` so the Sarvam-only install stays light.
- System: `ffmpeg` must be on PATH.
- Note in README: browser mic capture needs HTTPS; for local dev use `localhost` (exempt) or an ngrok tunnel.
  The frontend recorder itself is out of scope; the upload endpoint accepts webm/wav/mp3 so a
  MediaRecorder blob works as-is.

## Steps

1. Scaffold `settings.py`, `db.py`, `storage.py`, `audio.py`, `main.py` with the 4 routes and a stub
   ASR/MT that echoes. Verify upload → DB rows end-to-end before any model.
2. Add `asr/sarvam.py` + `mt/sarvam.py`; test with a 10 s Hindi and Marathi wav. This is the first
   real end-to-end milestone.
3. Add `asr/bhashini.py` + `mt/bhashini.py` (free secondary), then `asr/local.py` + `mt/local.py`
   (offline fallback); test with the same wavs; compare outputs against Sarvam.
4. Wire `chain.py` (LangChain sequence) into the upload route; add `model_runs` timing.
5. Doctor edit endpoint + GET transcripts view.
6. README with setup, env, curl examples; `.env.example`.

## Verification

- `uvicorn app.main:app --reload`, then:
  - `curl -X POST localhost:8000/consultations` → id
  - `curl -F file=@hindi.wav -F language=hi -F speaker=patient localhost:8000/consultations/{id}/audio`
    → JSON with `raw_text` (Devanagari) and `translated_text` (English)
  - same with `language=mr` and `language=en` (en must have no translation row)
  - `PUT /transcripts/{id}` with edited text → `doctor_edits` row; GET shows raw + edited.
- Switch `ASR_BACKEND=bhashini` and then `local`, repeat the hi/mr uploads; results should be comparable.
  With a non-Sarvam ASR and `MT_BACKEND=sarvam`, confirm the text MT path is hit (model_runs shows mayura).
- One small `test_chain.py`: monkeypatch the ASR/MT backends with fakes and assert the chain skips
  translation for `en` and persists rows for `hi`. This is the single required self-check.
- Failure path: wrong Bhashini key → 502 with a readable message, `model_runs.status = "error"`.
