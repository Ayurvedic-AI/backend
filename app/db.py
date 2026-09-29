from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.settings import settings


class Base(DeclarativeBase):
    pass


class Consultation(Base):
    __tablename__ = "consultations"
    id: Mapped[int] = mapped_column(primary_key=True)
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
    audio_file_id: Mapped[int] = mapped_column(ForeignKey("audio_files.id"))
    stage: Mapped[str]          # asr | mt
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


engine = create_engine(settings.database_url)
