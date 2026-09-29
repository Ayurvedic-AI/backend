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

```bash
curl -X POST localhost:8000/consultations                       # -> {"id": 1}
curl -F file=@hindi.wav -F language=hi -F speaker=patient localhost:8000/consultations/1/audio
# -> {"transcript_id": 1, "raw_text": "...", "translation_id": 1, "translated_text": "..."}
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

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Later

- Postgres (default): create DB `ayurvedic_ai` and set `DATABASE_URL` in `.env`. pgvector: `sudo apt install postgresql-17-pgvector`.
- S3: `STORAGE=s3 S3_BUCKET=...` (boto3 credentials from the environment).
- IndicWhisper instead of IndicConformer: convert a vistaar checkpoint with `ct2-transformers-converter`
  and point `faster_whisper.WhisperModel` at it in `app/asr/local.py`.
