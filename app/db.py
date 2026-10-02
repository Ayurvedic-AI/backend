from datetime import date, datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import JSON, ForeignKey, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.settings import settings


class Base(DeclarativeBase):
    pass


class Patient(Base):
    """Registry. Public id is "AYU-0001" (= f"AYU-{id:04d}"); the integer PK is never exposed.
    Field set mirrors frontend/src/features/patients/api/patients-stubs.ts."""
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str]
    date_of_birth: Mapped[date]
    gender: Mapped[str]             # male | female | other
    phone: Mapped[str]              # 10 national digits
    email: Mapped[str | None]
    preferred_language: Mapped[str] # hi | mr | en
    address_line: Mapped[str | None]
    city: Mapped[str | None]
    state: Mapped[str | None]
    pin_code: Mapped[str | None]
    prakriti: Mapped[str]           # dosha values as in app.pariksha, or "unknown"
    chief_complaint: Mapped[str | None]
    allergies: Mapped[list] = mapped_column(JSON)
    conditions: Mapped[list] = mapped_column(JSON)
    medications: Mapped[list] = mapped_column(JSON)
    blood_group: Mapped[str]
    status: Mapped[str]             # active | inactive
    notes: Mapped[str | None] = mapped_column(Text)
    registered_on: Mapped[date] = mapped_column(default=date.today)


class Consultation(Base):
    __tablename__ = "consultations"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AudioFile(Base):
    __tablename__ = "audio_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"))
    speaker: Mapped[str]
    language: Mapped[str]
    file_url: Mapped[str]
    duration_seconds: Mapped[float | None]
    sample_rate: Mapped[int | None]
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Transcript(Base):
    __tablename__ = "transcripts"
    id: Mapped[int] = mapped_column(primary_key=True)
    audio_file_id: Mapped[int] = mapped_column(ForeignKey("audio_files.id"))
    model_name: Mapped[str]
    language: Mapped[str]
    raw_text: Mapped[str] = mapped_column(Text)


class Translation(Base):
    __tablename__ = "translations"
    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id"))
    source_language: Mapped[str]
    target_language: Mapped[str]
    translated_text: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str]


class DoctorEdit(Base):
    __tablename__ = "doctor_edits"
    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id"))
    translation_id: Mapped[int | None] = mapped_column(ForeignKey("translations.id"))
    original_text: Mapped[str] = mapped_column(Text)
    edited_text: Mapped[str] = mapped_column(Text)
    edited_by: Mapped[str]
    edited_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    audio_file_id: Mapped[int | None] = mapped_column(ForeignKey("audio_files.id"))      # asr | mt runs
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultations.id"))  # rag runs
    stage: Mapped[str]          # asr | mt | rag
    backend: Mapped[str]
    model_name: Mapped[str]
    duration_ms: Mapped[int]
    status: Mapped[str]         # ok | error
    error: Mapped[str | None]


class Examination(Base):
    """Ashtavidha Pariksha findings. Append-only: each save inserts a row, GET returns the latest."""
    __tablename__ = "examinations"
    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"))
    examiner: Mapped[str]
    findings: Mapped[dict] = mapped_column(JSON)   # {section: {field: value}}, keys per app.pariksha
    recorded_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Verse(Base):
    """Charaka Samhita verse + embedding (bge-small-en-v1.5, 384-d). Filled by `python -m app.rag data/charaka`."""
    __tablename__ = "verses"
    id: Mapped[int] = mapped_column(primary_key=True)
    sthana: Mapped[str]         # e.g. Sutrasthana
    chapter: Mapped[str]        # e.g. 27a (the dataset splits long chapters into a..l files)
    verse_id: Mapped[str]       # kept as text: "4-5", "8-14½", "12-(1)" occur
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(VECTOR(384))


engine = create_engine(settings.database_url)


def get_db():
    with Session(engine) as s:
        yield s
