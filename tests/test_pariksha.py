import os

os.environ.update(DATABASE_URL="sqlite:///./test.db", STORAGE_DIR="./data/test_audio",
                  ASR_BACKEND="sarvam", MT_BACKEND="sarvam", SARVAM_API_KEY="x")

from fastapi.testclient import TestClient

from app.main import app


def test_examination_round_trip_and_validation():
    c = TestClient(app)
    cid = c.post("/consultations").json()["id"]
    schema = c.get("/pariksha/schema").json()
    assert set(schema) == {"nadi", "mutra", "mala", "jihva", "shabda", "sparsha", "drik", "akriti", "agni", "mala_assessment"}
    assert schema["agni"]["group"] == "assessment" and schema["agni"]["question"].startswith("How is your appetite")
    assert c.get(f"/consultations/{cid}/examination").json() == {}

    findings = {"nadi": {"pulse_rate": 72, "rhythm": "regular"}, "drik": {"jaundice_flag": True},
                "agni": {"agni": "mandagni", "symptoms": ["nausea", "low appetite"], "notes": "n"},
                "mala_assessment": {"frequency": "irregular", "concerns": ["constipation"], "dosha_pattern": "vata"}}
    r = c.put(f"/consultations/{cid}/examination", json={"examiner": "dr", "findings": findings})
    assert r.status_code == 200, r.text
    got = c.get(f"/consultations/{cid}/examination").json()
    assert got["findings"] == findings and got["examiner"] == "dr"

    # second save wins (append-only, latest returned)
    c.put(f"/consultations/{cid}/examination", json={"examiner": "dr", "findings": {"nadi": {"pulse_rate": 80}}})
    assert c.get(f"/consultations/{cid}/examination").json()["findings"] == {"nadi": {"pulse_rate": 80}}

    r = c.put(f"/consultations/{cid}/examination", json={"examiner": "dr", "findings": {"nadi": {"bogus": 1}}})
    assert r.status_code == 400 and "nadi.bogus" in r.json()["detail"]
    assert c.put(f"/consultations/{cid}/examination", json={"examiner": "dr", "findings": {"xyz": {}}}).status_code == 400
    r = c.put(f"/consultations/{cid}/examination", json={"examiner": "dr", "findings": {"agni": {"symptoms": "nausea"}}})
    assert r.status_code == 400 and "agni.symptoms" in r.json()["detail"]   # multi must be a list
    assert c.put("/consultations/999999/examination", json={"examiner": "dr", "findings": {}}).status_code == 404

    photo = {"file": ("t.jpg", b"\xff\xd8fake", "image/jpeg")}
    assert c.post(f"/consultations/{cid}/examination/jihva-photo", files=photo).status_code == 400
    r = c.post(f"/consultations/{cid}/examination/jihva-photo", files=photo, data={"consent": "true"})
    assert r.status_code == 200 and r.json()["photo_url"].endswith(".jpg")
