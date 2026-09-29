"""Ashtavidha Pariksha + doctor-led assessment field schema.
Field type: "int" | "bool" | "text" | [options] (select) | {"one": {value: description}} (radio)
            | {"multi": [options]} (checkbox group, stored as a list).
Single source of truth: the server validates keys against it, the UI renders the form from it."""

PARIKSHA = {
    "nadi": ("Nadi Pariksha · pulse", {
        "pulse_rate": "int", "rhythm": ["regular", "irregular", "irregularly irregular"],
        "strength": ["weak", "moderate", "strong"],
        "dosha_observation": ["vata", "pitta", "kapha", "vata-pitta", "pitta-kapha", "vata-kapha", "tridosha"],
        "method": ["manual", "device"], "notes": "text"}),
    "mutra": ("Mutra Pariksha · urine", {
        "frequency_per_day": "int", "quantity": ["scanty", "normal", "excess"],
        "colour": ["pale", "yellow", "dark yellow", "red", "cloudy"],
        "burning": "bool", "urgency": "bool", "nocturia_per_night": "int",
        "foam_sediment": ["none", "foam", "sediment", "both"], "lab_report": "text", "notes": "text"}),
    "mala": ("Mala Pariksha · stool", {
        "frequency_per_day": "int", "consistency": ["hard", "formed", "soft", "loose", "watery"],
        "colour": ["brown", "pale", "yellow", "green", "black", "red"], "odour": ["normal", "foul"],
        "bowel_pattern": ["normal", "constipation", "loose stools", "alternating"],
        "mucus": "bool", "blood": "bool", "incomplete_evacuation": "bool", "notes": "text"}),
    "jihva": ("Jihva Pariksha · tongue", {
        "colour": ["pale", "pink", "red", "bluish"], "coating": ["none", "white", "yellow", "brown", "black"],
        "moisture": ["dry", "normal", "moist"], "cracks": "bool", "swelling": "bool", "tremor": "bool",
        "photo_url": "text",  # set by the photo endpoint (consent-gated)
        "notes": "text"}),
    "shabda": ("Shabda Pariksha · voice", {
        "voice": ["clear", "weak", "hoarse", "nasal", "tremulous"],
        "speech_comfort": ["comfortable", "effortful"], "breathless_while_speaking": "bool", "notes": "text"}),
    "sparsha": ("Sparsha Pariksha · touch", {
        "temperature": ["cold", "normal", "warm", "hot"], "skin": ["dry", "normal", "oily"],
        "tenderness": "bool", "sweating": ["reduced", "normal", "excess"], "texture": ["smooth", "rough"],
        "oedema": "bool", "notes": "text"}),
    "drik": ("Drik Pariksha · eyes", {
        "sclera_colour": ["white", "yellow", "red"], "conjunctival_pallor": "bool",
        "dryness": "bool", "redness": "bool", "vision_complaint": "text",
        "jaundice_flag": "bool", "pallor_flag": "bool",  # referral flags
        "notes": "text"}),
    "akriti": ("Akriti Pariksha · build", {
        "build": ["lean", "medium", "heavy"], "nourishment": ["under", "normal", "over"],
        "posture": ["normal", "stooped", "other"], "gait": ["normal", "abnormal"], "oedema": "bool",
        "deformity": "text", "facial_appearance": "text", "strength": ["weak", "moderate", "strong"],
        "notes": "text"}),
}

# Doctor-led assessments: (label, question the doctor asks the patient, fields). Patient-reported.
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
             "or loose, and is there any straining, pain, mucus or blood?",
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

SECTIONS = {**{k: (label, None, fields) for k, (label, fields) in PARIKSHA.items()}, **ASSESSMENTS}


def unknown_keys(findings: dict) -> str | None:
    """Return the first invalid 'section' or 'section.field' key, or None when all keys are valid.
    A "multi" field must hold a list."""
    for section, fields in findings.items():
        if section not in SECTIONS:
            return section
        for f, v in fields.items():
            t = SECTIONS[section][2].get(f)
            if t is None or (isinstance(t, dict) and "multi" in t and not isinstance(v, list)):
                return f"{section}.{f}"
    return None
