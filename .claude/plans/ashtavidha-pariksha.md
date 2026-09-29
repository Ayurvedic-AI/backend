# Ashtavidha Pariksha capture (8-fold examination) after the transcript

## Context

Transcription MVP is done (Sarvam ASR → English, Postgres, doctor edits, browser recorder).
Next: after the transcript, the doctor records the eight classical examination findings for the
consultation. Structured fields where the user's table gives discrete values, free text where it says
"observation" / "notes", one photo upload (tongue) gated on explicit consent, and two referral flags
(jaundice, pallor) that the UI highlights.

Assumptions (say so if wrong):
- One examination record per save, **append-only** (same ethic as `doctor_edits`: nothing is overwritten;
  GET returns the latest). No per-section save; one "Save examination" button for all eight.
- Findings are doctor-entered, so validation = reject unknown field keys only. No per-value enum
  enforcement on the server; the UI's `<select>` already constrains choices.
- Modern urine report = free-text field. No lab-file upload.
- No auth yet; `examiner` is a free-text name like `edited_by` today.

## Data

One new table, findings stored as JSON (works on Postgres JSONB and on SQLite for tests):

```
examinations(id, consultation_id FK, examiner, findings JSON, recorded_at)
```

`findings` = `{"nadi": {...}, "mutra": {...}, ..., "akriti": {...}}`, keys limited to the schema below.

## Field schema — single source of truth

`app/pariksha.py`: one dict. Server uses it to validate keys; the UI fetches it and renders the form,
so the ~60 fields are declared once, not twice.

```python
# field type: "int" | "bool" | "text" | [options...]
PARIKSHA = {
  "nadi":    ("Nadi Pariksha · pulse", {
      "pulse_rate": "int", "rhythm": ["regular", "irregular", "irregularly irregular"],
      "strength": ["weak", "moderate", "strong"],
      "dosha_observation": ["vata", "pitta", "kapha", "vata-pitta", "pitta-kapha", "vata-kapha", "tridosha"],
      "method": ["manual", "device"], "notes": "text"}),
  "mutra":   ("Mutra Pariksha · urine", {
      "frequency_per_day": "int", "quantity": ["scanty", "normal", "excess"],
      "colour": ["pale", "yellow", "dark yellow", "red", "cloudy"],
      "burning": "bool", "urgency": "bool", "nocturia_per_night": "int",
      "foam_sediment": ["none", "foam", "sediment", "both"], "lab_report": "text", "notes": "text"}),
  "mala":    ("Mala Pariksha · stool", {
      "frequency_per_day": "int", "consistency": ["hard", "formed", "soft", "loose", "watery"],
      "colour": ["brown", "pale", "yellow", "green", "black", "red"], "odour": ["normal", "foul"],
      "bowel_pattern": ["normal", "constipation", "loose stools", "alternating"],
      "mucus": "bool", "blood": "bool", "incomplete_evacuation": "bool", "notes": "text"}),
  "jihva":   ("Jihva Pariksha · tongue", {
      "colour": ["pale", "pink", "red", "bluish"], "coating": ["none", "white", "yellow", "brown", "black"],
      "moisture": ["dry", "normal", "moist"], "cracks": "bool", "swelling": "bool", "tremor": "bool",
      "photo_url": "text",     # set by the photo endpoint, read-only in the UI
      "notes": "text"}),
  "shabda":  ("Shabda Pariksha · voice", {
      "voice": ["clear", "weak", "hoarse", "nasal", "tremulous"],
      "speech_comfort": ["comfortable", "effortful"], "breathless_while_speaking": "bool", "notes": "text"}),
  "sparsha": ("Sparsha Pariksha · touch", {
      "temperature": ["cold", "normal", "warm", "hot"], "skin": ["dry", "normal", "oily"],
      "tenderness": "bool", "sweating": ["reduced", "normal", "excess"], "texture": ["smooth", "rough"],
      "oedema": "bool", "notes": "text"}),
  "drik":    ("Drik Pariksha · eyes", {
      "sclera_colour": ["white", "yellow", "red"], "conjunctival_pallor": "bool",
      "dryness": "bool", "redness": "bool", "vision_complaint": "text",
      "jaundice_flag": "bool", "pallor_flag": "bool",   # referral flags, highlighted in UI
      "notes": "text"}),
  "akriti":  ("Akriti Pariksha · build", {
      "build": ["lean", "medium", "heavy"], "nourishment": ["under", "normal", "over"],
      "posture": ["normal", "stooped", "other"], "gait": ["normal", "abnormal"], "oedema": "bool",
      "deformity": "text", "facial_appearance": "text", "strength": ["weak", "moderate", "strong"],
      "notes": "text"}),
}
```

## API (main.py, 4 routes)

```
GET  /pariksha/schema                              -> PARIKSHA (UI renders from it)
PUT  /consultations/{cid}/examination              -> {examiner, findings}  → inserts row, returns {id}
                                                      400 on unknown pariksha/field key, 404 bad cid
GET  /consultations/{cid}/examination              -> latest row or {} (404 bad cid)
POST /consultations/{cid}/examination/jihva-photo  -> multipart file + consent=true (400 if not true)
                                                      saves via storage.save_audio (bytes→path, name-agnostic),
                                                      returns {photo_url}; UI puts it into findings.jihva.photo_url
```

Photo consent is enforced server-side, not just as a checkbox. The stored path goes into the findings
JSON; no separate table.

## UI (index.html, one new section)

Below the transcript cards: `<h3>Ashtavidha Pariksha</h3>`, then eight `<details>` fieldsets rendered
from `/pariksha/schema` by ~30 lines of JS: `int` → `<input type=number>`, `bool` → checkbox,
`text` → `<textarea>` (or `<input>` for one-liners), list → `<select>` with a blank first option.
Jihva section additionally has a file input + "Patient consented to photo" checkbox + Upload button.
Drik referral flags get a red label. One `Examiner` input and one **Save examination** button that
PUTs the whole form. On consultation load/new, GET the latest examination and pre-fill.

Native form controls only, no library. `<details>` keeps the eight sections from swamping the page.

## Files touched

```
app/pariksha.py          new, the schema dict (~50 lines)
app/db.py                +Examination model (~8 lines)
app/main.py              +4 routes (~45 lines)
app/static/index.html    +form section + renderer + save/load (~70 lines)
tests/test_pariksha.py   new, one test (~25 lines)
README.md                +examination curl lines
```

`Base.metadata.create_all` at startup creates the table; still no Alembic.

## Steps

1. `pariksha.py` + `db.Examination` + PUT/GET routes → verify: curl PUT with a partial findings body,
   GET returns it; PUT with `{"nadi": {"bogus": 1}}` → 400.
2. Photo route → verify: POST without `consent=true` → 400; with it → file lands in `STORAGE_DIR`,
   `photo_url` returned.
3. UI section → verify in browser: schema renders 8 sections, save round-trips, reload pre-fills,
   jaundice flag shows red.
4. `test_pariksha.py`: PUT → GET round-trip, unknown key → 400, photo without consent → 400.
5. README curl lines.

## Verification

- `.venv/bin/python -m pytest -q` → all pass (existing 5 + new).
- Browser: record a clip → transcript card appears → fill Nadi + Drik (tick jaundice) → Save →
  refresh page, enter the same consultation id → fields pre-filled, jaundice highlighted.

## Deferred (say so if you want it now)

- Per-section save / edit history view of examinations (rows already append-only, view is trivial later).
- Server-side enum enforcement (build pydantic models from the dict when a non-UI client appears).
- Auto-suggesting findings from the transcript with an LLM — this is the natural next step after
  the fields exist, and slots into `chain.py`.
