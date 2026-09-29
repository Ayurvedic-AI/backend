# Doctor-led assessments after the transcript: Agni and Mala

## Context

The Ashtavidha Pariksha form is live (schema dict → `/pariksha/schema` → form rendered in the browser,
findings saved as JSON in `examinations`). Add two short doctor-led assessments below it. Each one shows
the question the doctor asks the patient, then a small set of checkboxes and a note. The doctor fills
them from the patient's answer, so they are patient-reported, unlike the pariksha sections which are
examiner-observed.

Two things worth deciding up front:

1. **Mala overlap.** The existing "Mala Pariksha · stool" section already has frequency, consistency,
   mucus, blood, constipation and incomplete evacuation. The new Mala assessment repeats those in
   questionnaire form and adds pain, bloating and a dosha-pattern read. Plan below **keeps both** as
   asked: Mala Pariksha = what the doctor observes, Mala assessment = what the patient reports. If you
   would rather have one stool section, say so and I fold the assessment into the existing `mala`
   section (drops colour/odour or keeps them, your call). That makes the form shorter.
2. **Mala question.** You gave the Agni question. I drafted a Mala one below in the same style;
   edit it freely.

## Data

No schema migration. The two assessments are two more top-level keys in the same `findings` JSON:

```json
{"nadi": {...}, ..., "akriti": {...},
 "agni": {"agni": "mandagni", "symptoms": ["bloating/gas", "heaviness after meals"], "notes": "..."},
 "mala_assessment": {"frequency": "irregular", "consistency": "hard/dry",
                     "concerns": ["constipation", "incomplete evacuation"],
                     "dosha_pattern": "vata", "notes": "..."}}
```

Same table, same PUT/GET routes, same append-only rule.

## Schema additions (`app/pariksha.py`)

Two new field types, needed because the assessment form is checkbox-driven:

| type                          | stored as         | rendered as                                          |
|-------------------------------|-------------------|------------------------------------------------------|
| `{"one": {value: description}}` | one string      | radio group, description shown next to each option   |
| `{"multi": [options]}`          | list of strings | checkbox group; ticking "none" clears the others     |

Existing types (`int`, `bool`, `text`, `[options]` select) stay as they are.

```python
ASSESSMENTS = {
    "agni": ("Agni assessment · appetite & digestion",
             "How is your appetite and digestion most days? After meals, do you feel comfortable, "
             "heavy, bloated, acidic, or is your appetite irregular?",
             {"agni": {"one": {
                 "samagni": "appetite and digestion generally comfortable / regular",
                 "mandagni": "low appetite, heaviness, slow digestion",
                 "tikshnagni": "very strong appetite, burning / acidity, intolerance of delayed meals",
                 "vishamagni": "irregular appetite / digestion, gas, bloating, variable bowel habits",
                 "not assessed": ""}},
              "symptoms": {"multi": ["bloating/gas", "acidity/burning", "heaviness after meals",
                                     "low appetite", "irregular hunger", "nausea", "none"]},
              "notes": "text"}),
    "mala_assessment": ("Mala assessment · bowel habit",
             "How are your bowel movements most days? How often do you go, is the stool formed, hard "
             "or loose, and is there any straining, pain, mucus or blood?",           # drafted, edit me
             {"frequency": {"one": {"once daily": "", "more than once daily": "",
                                    "less than once daily": "", "irregular": ""}},
              "consistency": {"one": {"normal/formed": "", "hard/dry": "", "loose/watery": "", "variable": ""}},
              "concerns": {"multi": ["constipation", "incomplete evacuation", "pain while passing stool",
                                     "bloating/gas", "mucus", "blood reported", "none"]},
              "dosha_pattern": {"one": {"vata": "vata-related pattern suspected",
                                        "pitta": "pitta-related pattern suspected",
                                        "kapha": "kapha-related pattern suspected",
                                        "mixed": "mixed / unclear", "not assessed": ""}},
              "notes": "text"}),
}
```

`unknown_keys()` checks against `PARIKSHA | ASSESSMENTS`. Value-level validation stays UI-only, as
before, except one cheap server check: a `multi` field must be a list (one `isinstance`), so a client
cannot store a bare string where the UI expects a list.

## API

`GET /pariksha/schema` returns both groups, each entry gaining `"group": "pariksha" | "assessment"`
and an optional `"question"`. PUT/GET examination unchanged.

## UI (`index.html`)

- After the eight pariksha `<details>`, an `<h3>Doctor-led assessments</h3>` and two `<details open>`
  (open by default, they are short and are the part the doctor fills while talking).
- Inside each: the question in a highlighted box, `Ask the patient: "…"`, then the fields.
- `one` → radio inputs named `section.field`, label = option, plus the description in grey when
  present. `multi` → checkboxes named `section.field[]`, label = option; ticking "none" unchecks the
  rest and ticking anything else unchecks "none" (3 lines of JS).
- Save: the existing collector gains two cases: radios → the checked value, `[]` checkboxes → list of
  checked values. Load: pre-tick from the saved lists / values. Everything else reuses what is there.
- Single **Save examination** button still saves pariksha + assessments together.

## Files touched

```
app/pariksha.py          +ASSESSMENTS dict, unknown_keys covers both, multi-is-list check   (~35 lines)
app/main.py              schema route merges both groups                                     (~3 lines)
app/static/index.html    question box, radio/multi renderers, save/load for them, "none" rule (~40 lines)
tests/test_pariksha.py   +assertions: assessment round-trip, "symptoms": "x" (not a list) → 400 (~8 lines)
README.md                one line + example body                                              (~4 lines)
```

## Steps

1. Schema + validator → verify: PUT `{"agni": {"agni": "mandagni", "symptoms": ["nausea"]}}` → 200,
   GET returns it; PUT `{"agni": {"symptoms": "nausea"}}` → 400; unknown key still 400.
2. Schema route → verify: `curl /pariksha/schema | jq '.agni.question'` prints the question.
3. UI → verify in browser: two open assessment blocks under the pariksha list, question visible,
   radio picks one, ticking "none" clears other symptoms, save → reload → pre-ticked.
4. Test additions, README.

## Verification

- `.venv/bin/python -m pytest -q` → 6 pass (test_pariksha extended, not a new file).
- Browser round-trip as in step 3, plus one pariksha field saved in the same click to prove the two
  groups share a save.

## Deferred

- Pre-ticking symptoms from the transcript with an LLM. The English transcript plus this schema is a
  clean extraction prompt; it would slot into `chain.py` as a third step. Say when.
- Folding Mala assessment into Mala Pariksha (see decision 1 above).
