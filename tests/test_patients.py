import os
from datetime import date

os.environ.update(DATABASE_URL="sqlite:///./test.db", STORAGE_DIR="./data/test_audio",
                  ASR_BACKEND="sarvam", MT_BACKEND="sarvam", SARVAM_API_KEY="x")

from fastapi.testclient import TestClient

from app.main import app

BODY = {"full_name": " Sunita Deshmukh ", "date_of_birth": "1978-03-12", "gender": "female", "phone": "9823456710",
        "preferred_language": "mr", "city": "Pune", "state": "Maharashtra", "pin_code": "411030",
        "prakriti": "vata-pitta", "chief_complaint": "Joint pain in knees", "allergies": ["Sesame oil"],
        "conditions": ["Hypothyroidism"], "medications": ["Thyroxine 50 mcg"], "blood_group": "B+"}


def test_patient_crud_and_last_visit():
    c = TestClient(app)
    r = c.post("/api/v1/patients", json=BODY)
    assert r.status_code == 201, r.text
    p = r.json()
    pid = p["id"]
    assert pid.startswith("AYU-") and len(pid) == 8 and p["full_name"] == "Sunita Deshmukh"
    assert p["registered_on"] == date.today().isoformat() and p["last_visit"] is None
    assert p["email"] is None and p["status"] == "active" and p["notes"] is None

    assert c.get("/api/v1/patients").json()[0]["id"] == pid                      # newest first
    assert c.get(f"/api/v1/patients/{pid}").json()["city"] == "Pune"

    r = c.put(f"/api/v1/patients/{pid}", json={**BODY, "city": "Nashik", "status": "inactive", "allergies": []})
    assert r.status_code == 200 and r.json()["city"] == "Nashik" and r.json()["allergies"] == []

    # validation mirrors the frontend zod schema
    assert c.post("/api/v1/patients", json={**BODY, "phone": "12345"}).status_code == 422
    assert c.post("/api/v1/patients", json={**BODY, "date_of_birth": "2999-01-01"}).status_code == 422
    assert c.post("/api/v1/patients", json={**BODY, "pin_code": "41"}).status_code == 422
    assert c.post("/api/v1/patients", json={**BODY, "gender": "x"}).status_code == 422
    assert c.post("/api/v1/patients", json={**BODY, "email": "nope"}).status_code == 422

    # a consultation linked to the patient sets last_visit
    cid = c.post("/consultations", json={"patient_id": pid}).json()["id"]
    assert cid and c.get(f"/api/v1/patients/{pid}").json()["last_visit"] == date.today().isoformat()
    assert c.post("/consultations").status_code == 200                           # anonymous still works
    assert c.post("/consultations", json={"patient_id": "AYU-9999"}).status_code == 404

    assert c.delete(f"/api/v1/patients/{pid}").status_code == 204
    assert c.get(f"/api/v1/patients/{pid}").status_code == 404
    assert c.put(f"/api/v1/patients/{pid}", json=BODY).status_code == 404
    assert c.delete("/api/v1/patients/bogus").status_code == 404
