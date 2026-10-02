# Consultation transcription MVP

Hindi / Marathi / English audio → original transcript → English translation → stored for doctor review.

## Setup

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt
cp .env.example .env            # add SARVAM_API_KEY
.venv/bin/uvicorn app.main:app --reload
```

Backends are chosen by env (`ASR_BACKEND`, `MT_BACKEND`):

| backend    | needs                                   | notes                                              |
|------------|-----------------------------------------|----------------------------------------------------|
| `sarvam`   | `SARVAM_API_KEY`                        | default; saaras:v3 does speech→English directly    |
| `bhashini` | `BHASHINI_USER_ID`, `BHASHINI_API_KEY`, ffmpeg | free dev keys from bhashini.gov.in          |
| `local`    | `requirements-local.txt`, ffmpeg        | IndicConformer + IndicTrans2 + faster-whisper on CPU |

Clips must be ≤ 30 s. Uploads may be wav/mp3/webm (a browser `MediaRecorder` blob works as-is; mic
capture needs HTTPS or `localhost`).

## API

Swagger UI at `/docs`; the OpenAPI document is at `/api/v1/openapi.json` (the path `frontend`'s
`bun run sdk:gen` fetches). Routes are tagged consultations / audio / transcripts / pariksha / verses
and operation ids are the handler names, so Orval emits `useCreateConsultation()` etc. CORS allows
`CORS_ORIGINS` (default `http://localhost:5173`).

```bash
curl -X POST localhost:8000/api/v1/patients -H 'content-type: application/json' \\
  -d '{"full_name":"Sunita Deshmukh","date_of_birth":"1978-03-12","gender":"female","phone":"9823456710","preferred_language":"mr"}'
# -> 201 {"id": "AYU-0001", "registered_on": "...", "last_visit": null, ...}; also GET (list / one), PUT, DELETE on /api/v1/patients[/{id}]
curl -X POST localhost:8000/consultations -H 'content-type: application/json' -d '{"patient_id":"AYU-0001"}'   # -> {"id": 1}; body optional
curl -F file=@hindi.wav -F speaker=patient localhost:8000/consultations/1/audio   # language defaults to auto
# -> {"transcript_id": 1, "raw_text": "...", "translation_id": 1, "translated_text": "...", "urgent": false, "red_flags": []}
curl localhost:8000/consultations/1/transcripts
curl -X PUT localhost:8000/transcripts/1 -H 'content-type: application/json' \
     -d '{"edited_text": "...", "edited_by": "dr.x", "translation_id": 1}'   # omit translation_id to edit the original
```

Ashtavidha Pariksha (8-fold examination) findings are recorded per consultation from the UI or:

```bash
curl localhost:8000/pariksha/schema                                   # sections + fields the UI renders
curl -X PUT localhost:8000/consultations/1/examination -H 'content-type: application/json' \
     -d '{"examiner": "dr.x", "findings": {"nadi": {"pulse_rate": 72, "rhythm": "regular"}, "drik": {"jaundice_flag": true}}}'
curl localhost:8000/consultations/1/examination                       # latest save
curl -F file=@tongue.jpg -F consent=true localhost:8000/consultations/1/examination/jihva-photo  # -> {"photo_url"}
```

Two doctor-led assessments (Agni, Mala) live in the same body under `agni` and `mala_assessment`, e.g.
`{"agni": {"agni": "mandagni", "symptoms": ["nausea"], "notes": "..."}}`; multi-choice fields are lists.
Field keys are validated against `app/pariksha.py`; saves are append-only (GET returns the latest).
The tongue photo upload is refused without `consent=true`.

Raw model output is never overwritten; edits append to `doctor_edits`. Every model call is logged in
`model_runs` with backend, model, duration and status.

## Verse retrieval (Charaka Samhita)

Needs the pgvector extension in Postgres (`sudo apt install postgresql-18-pgvector`; the app runs
`CREATE EXTENSION` itself). One-time ingest, ~5 min on CPU with bge-small-en-v1.5:

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/gita/Datasets /tmp/ds \
  && git -C /tmp/ds sparse-checkout set Ayurveda/charak-samhita && cp -r /tmp/ds/Ayurveda/charak-samhita data/charaka
.venv/bin/python -m app.rag data/charaka                         # -> ingested 8215 verses
curl "localhost:8000/consultations/1/verses?k=10"
# -> {"urgent": true, "red_flags": ["vomiting for days"], "advice": "...", "queries": ["patient says: ...", "tongue: ..."],
#     "verses": [{"ref": "Cikitsasthana 20.9", "matched": ["patient says"], "text": "..."}]}
```

`app/triage.py` screens the English transcript and referral fields for red flags (persistent vomiting,
bleeding, chest pain, jaundice...) as soon as a clip is uploaded, and again before any verse is shown. Each Pariksha section and the transcript
become one short clause; each clause is searched by cosine similarity and by Postgres full-text (the
keyword half lifted hit@5 from 15 to 19 of 20 on a local 20-query check) and the rankings are fused
(reciprocal rank fusion, patient's words weighted double). No LLM. Neutral findings (regular, normal,
moderate, method) are dropped from the query. The dataset is a scrape of the 1949 Gulabkunverba
translation with no stated licence, so it stays out of git (`data/` is ignored).

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Later

- Postgres (default): create DB `ayurvedic_ai` and set `DATABASE_URL` in `.env`. 
- S3: `STORAGE=s3 S3_BUCKET=...` (boto3 credentials from the environment).
- IndicWhisper instead of IndicConformer: convert a vistaar checkpoint with `ct2-transformers-converter`
  and point `faster_whisper.WhisperModel` at it in `app/asr/local.py`.
