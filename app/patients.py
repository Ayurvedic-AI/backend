"""Patient registry CRUD. Contract mirrors frontend/src/features/patients/api/patients-stubs.ts, so the Orval SDK
replaces the stubs 1:1 (operation ids -> usePatientsList / usePatientsCreate / usePatientsUpdate / usePatientsDelete)."""
import re
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import db
from app.db import get_db

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])

Prakriti = Literal["vata", "pitta", "kapha", "vata-pitta", "pitta-kapha", "vata-kapha", "tridosha", "unknown"]
BloodGroup = Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "unknown"]


class PatientIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date
    gender: Literal["male", "female", "other"]
    phone: str = Field(pattern=r"^\d{10}$")
    email: str | None = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    preferred_language: Literal["hi", "mr", "en"]
    address_line: str | None = Field(None, max_length=200)
    city: str | None = Field(None, max_length=80)
    state: str | None = None
    pin_code: str | None = Field(None, pattern=r"^\d{6}$")
    prakriti: Prakriti = "unknown"
    chief_complaint: str | None = Field(None, max_length=300)
    allergies: list[str] = []
    conditions: list[str] = []
    medications: list[str] = []
    blood_group: BloodGroup = "unknown"
    status: Literal["active", "inactive"] = "active"
    notes: str | None = Field(None, max_length=1000)

    @field_validator("full_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("full_name is required")
        return v.strip()

    @field_validator("date_of_birth")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("date_of_birth cannot be in the future")
        return v


class PatientOut(PatientIn):
    id: str                      # "AYU-0001"
    registered_on: date
    last_visit: date | None      # latest consultation, null until the first visit


def get_patient(s: Session, patient_id: str) -> db.Patient:
    m = re.fullmatch(r"AYU-(\d+)", patient_id)
    p = s.get(db.Patient, int(m[1])) if m else None
    if not p:
        raise HTTPException(404, "patient not found")
    return p


def _last_visits(s: Session) -> dict[int, date]:
    rows = s.execute(select(db.Consultation.patient_id, func.max(db.Consultation.created_at))
                     .where(db.Consultation.patient_id.is_not(None)).group_by(db.Consultation.patient_id))
    return {pid: ts.date() for pid, ts in rows}


def _out(p: db.Patient, last_visit: date | None) -> PatientOut:
    return PatientOut(id=f"AYU-{p.id:04d}", registered_on=p.registered_on, last_visit=last_visit,
                      **{f: getattr(p, f) for f in PatientIn.model_fields})


@router.get("", response_model=list[PatientOut])
def patients_list(s: Session = Depends(get_db)):
    """All patients, newest first. Search/filters are client-side (the list is small)."""
    visits = _last_visits(s)
    return [_out(p, visits.get(p.id)) for p in s.scalars(select(db.Patient).order_by(db.Patient.id.desc()))]


@router.get("/{patient_id}", response_model=PatientOut)
def patients_retrieve(patient_id: str, s: Session = Depends(get_db)):
    p = get_patient(s, patient_id)
    return _out(p, _last_visits(s).get(p.id))


@router.post("", response_model=PatientOut, status_code=201)
def patients_create(body: PatientIn, s: Session = Depends(get_db)):
    p = db.Patient(**body.model_dump())
    s.add(p)
    s.commit()
    return _out(p, None)


@router.put("/{patient_id}", response_model=PatientOut)
def patients_update(patient_id: str, body: PatientIn, s: Session = Depends(get_db)):
    p = get_patient(s, patient_id)
    for f, v in body.model_dump().items():
        setattr(p, f, v)
    s.commit()
    return _out(p, _last_visits(s).get(p.id))


@router.delete("/{patient_id}", status_code=204)
def patients_delete(patient_id: str, s: Session = Depends(get_db)):
    s.delete(get_patient(s, patient_id))   # consultations keep their rows, patient_id -> NULL
    s.commit()
    return Response(status_code=204)
