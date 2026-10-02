import time
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import chain, db, patients, rag, triage
from app.db import get_db
from app.pariksha import PARIKSHA, SECTIONS, unknown_keys
from app.asr.base import BackendError
from app.audio import wav_info
from app.settings import settings
from app.storage import save_audio

@asynccontextmanager
async def lifespan(_):
    rag._model()   # ~10 s once at boot instead of on the first doctor's search
    yield


app = FastAPI(title="Ayurvedic consultation API", version="0.1.0", lifespan=lifespan,
              openapi_url="/api/v1/openapi.json",              # what the frontend's `bun run sdk:gen` fetches
              generate_unique_id_function=lambda r: r.name)    # operationId = function name -> useCreateConsultation()
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(patients.router)
db.Base.metadata.create_all(db.engine)


@app.exception_handler(BackendError)
def backend_error(_, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse("app/static/index.html")


class ConsultationIn(BaseModel):
    patient_id: str | None = None   # "AYU-0001"; omit for an anonymous consultation


class ConsultationOut(BaseModel):
    id: int
    patient_id: str | None      # "AYU-0001", or null for an anonymous consultation
    created_at: datetime
    urgent: bool                # red-flag screen over the latest examination + transcripts (no verse search)


@app.get("/consultations", tags=["consultations"], response_model=list[ConsultationOut])
def list_consultations(s: Session = Depends(get_db)):
    """All consultations, newest first, each with its red-flag screen so the list can mark urgent ones."""
    out = []
    for c in s.scalars(select(db.Consultation).order_by(db.Consultation.id.desc())):
        # ponytail: one examination + one transcript query per consultation; paginate when the list grows
        findings = get_examination(c.id, s).get("findings", {})
        queries = rag.build_queries(findings, list_transcripts(c.id, s))
        said = queries[0] if queries and queries[0].startswith("patient says") else ""
        out.append(ConsultationOut(id=c.id, patient_id=f"AYU-{c.patient_id:04d}" if c.patient_id else None,
                                   created_at=c.created_at, urgent=bool(triage.red_flags(findings, said))))
    return out


@app.post("/consultations", tags=["consultations"])
def create_consultation(body: ConsultationIn | None = None, s: Session = Depends(get_db)):
    c = db.Consultation(patient_id=patients.get_patient(s, body.patient_id).id if body and body.patient_id else None)
    s.add(c)
    s.commit()
    return {"id": c.id}


@app.post("/consultations/{cid}/audio", tags=["audio"])
def upload_audio(
    cid: int,
    file: UploadFile = File(...),
    language: Literal["auto", "hi", "mr", "en"] = Form("auto"),
    speaker: str = Form("conversation"),  # ponytail: no diarization; Sarvam batch job API has it
    s: Session = Depends(get_db),
):
    if not s.get(db.Consultation, cid):
        raise HTTPException(404, "consultation not found")
    if language == "auto" and settings.asr_backend != "sarvam":
        raise HTTPException(400, "language auto-detect needs ASR_BACKEND=sarvam")
    path = save_audio(file.file.read(), file.filename or "audio")
    duration, sr = wav_info(path)
    if duration and duration > 30:
        raise HTTPException(413, "clip longer than 30 s; split it first")
    audio = db.AudioFile(consultation_id=cid, speaker=speaker, language=language,
                         file_url=path, duration_seconds=duration, sample_rate=sr)
    s.add(audio)
    s.flush()

    inp = {"path": path, "lang": language}
    try:
        out = chain.pipeline.invoke(inp)
    finally:  # persist model_runs even on failure
        s.add_all(db.ModelRun(audio_file_id=audio.id, **r) for r in inp.get("runs", []))
        s.commit()

    t = db.Transcript(audio_file_id=audio.id, model_name=out["transcript"].model_name,
                      language=inp["lang"], raw_text=out["transcript"].text)
    s.add(t)
    s.flush()
    tr = None
    if out["translation"]:
        tr = db.Translation(transcript_id=t.id, source_language=inp["lang"], target_language="en",
                            translated_text=out["translation"].text, model_name=out["translation"].model_name)
        s.add(tr)
    s.commit()
    english = tr.translated_text if tr else t.raw_text if t.language == "en" else ""
    flags = triage.red_flags(get_examination(cid, s).get("findings", {}), f"patient says: {english}")
    return {"audio_file_id": audio.id, "transcript_id": t.id, "language": t.language, "raw_text": t.raw_text,
            "translation_id": tr.id if tr else None, "translated_text": tr.translated_text if tr else None,
            "urgent": bool(flags), "red_flags": flags}


@app.get("/consultations/{cid}/transcripts", tags=["transcripts"])
def list_transcripts(cid: int, s: Session = Depends(get_db)):
    rows = s.execute(
        select(db.Transcript, db.AudioFile, db.Translation)
        .join(db.AudioFile, db.Transcript.audio_file_id == db.AudioFile.id)
        .outerjoin(db.Translation, db.Translation.transcript_id == db.Transcript.id)
        .where(db.AudioFile.consultation_id == cid)
        .order_by(db.AudioFile.uploaded_at)
    ).all()

    def latest_edit(transcript_id, translation_id):
        e = s.scalars(
            select(db.DoctorEdit)
            .where(db.DoctorEdit.transcript_id == transcript_id, db.DoctorEdit.translation_id == translation_id)   # == None compiles to IS NULL
            .order_by(db.DoctorEdit.edited_at.desc())
        ).first()
        return e.edited_text if e else None

    return [{
        "transcript_id": t.id, "speaker": a.speaker, "language": t.language,
        "raw_text": t.raw_text, "edited_text": latest_edit(t.id, None),
        "translation_id": tr.id if tr else None,
        "translated_text": tr.translated_text if tr else None,
        "edited_translation": latest_edit(t.id, tr.id) if tr else None,
    } for t, a, tr in rows]


class EditIn(BaseModel):
    edited_text: str
    edited_by: str
    translation_id: int | None = None   # set to edit the English text instead of the original


@app.put("/transcripts/{tid}", tags=["transcripts"])
def edit_transcript(tid: int, body: EditIn, s: Session = Depends(get_db)):
    t = s.get(db.Transcript, tid)
    if not t:
        raise HTTPException(404, "transcript not found")
    original = t.raw_text
    if body.translation_id:
        tr = s.get(db.Translation, body.translation_id)
        if not tr or tr.transcript_id != tid:
            raise HTTPException(404, "translation not found")
        original = tr.translated_text
    e = db.DoctorEdit(transcript_id=tid, translation_id=body.translation_id, original_text=original,
                      edited_text=body.edited_text, edited_by=body.edited_by)
    s.add(e)
    s.commit()
    return {"edit_id": e.id}


@app.get("/pariksha/schema", tags=["pariksha"])
def pariksha_schema():
    return {k: {"label": label, "question": q, "group": "pariksha" if k in PARIKSHA else "assessment",
                "fields": fields} for k, (label, q, fields) in SECTIONS.items()}


class ExaminationIn(BaseModel):
    examiner: str
    findings: dict[str, dict]


@app.put("/consultations/{cid}/examination", tags=["pariksha"])
def save_examination(cid: int, body: ExaminationIn, s: Session = Depends(get_db)):
    if not s.get(db.Consultation, cid):
        raise HTTPException(404, "consultation not found")
    if bad := unknown_keys(body.findings):
        raise HTTPException(400, f"unknown pariksha field: {bad}")
    e = db.Examination(consultation_id=cid, examiner=body.examiner, findings=body.findings)
    s.add(e)
    s.commit()
    return {"id": e.id}


@app.get("/consultations/{cid}/examination", tags=["pariksha"])
def get_examination(cid: int, s: Session = Depends(get_db)):
    if not s.get(db.Consultation, cid):
        raise HTTPException(404, "consultation not found")
    e = s.scalars(select(db.Examination).where(db.Examination.consultation_id == cid)
                  .order_by(db.Examination.id.desc())).first()
    return {"id": e.id, "examiner": e.examiner, "findings": e.findings, "recorded_at": e.recorded_at} if e else {}


@app.get("/consultations/{cid}/verses", tags=["verses"])
def matching_verses(cid: int, k: int = 10, s: Session = Depends(get_db)):
    """Red-flag screen + top-k Charaka Samhita verses for the latest examination and transcripts. No LLM."""
    findings = get_examination(cid, s).get("findings", {})
    queries = rag.build_queries(findings, list_transcripts(cid, s))
    if not queries:
        raise HTTPException(400, "nothing to search: save an examination or upload audio first")
    flags = triage.red_flags(findings, queries[0] if queries[0].startswith("patient says") else "")
    t0 = time.perf_counter()
    hits = rag.search(s, queries, k)
    s.add(db.ModelRun(consultation_id=cid, stage="rag", backend="local", model_name=rag.MODEL,
                      duration_ms=int((time.perf_counter() - t0) * 1000), status="ok"))
    s.commit()
    return {
        "urgent": bool(flags), "red_flags": flags,
        "advice": "Red flags present: assess for urgent medical care before any Ayurvedic interpretation." if flags else None,
        "queries": queries,
        "verses": [{"ref": f"{v.sthana} {v.chapter}.{v.verse_id}", "matched": why, "text": v.text} for v, why in hits],
    }


@app.post("/consultations/{cid}/examination/jihva-photo", tags=["pariksha"])
def upload_jihva_photo(cid: int, file: UploadFile = File(...), consent: bool = Form(False),
                       s: Session = Depends(get_db)):
    if not s.get(db.Consultation, cid):
        raise HTTPException(404, "consultation not found")
    if not consent:
        raise HTTPException(400, "tongue photo needs explicit patient consent (consent=true)")
    return {"photo_url": save_audio(file.file.read(), file.filename or "tongue.jpg")}
