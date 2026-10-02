from app.rag import build_queries, clean
from app.triage import red_flags


def test_clean_rejoins_text_leaked_into_verse_id():
    v = {"verse_id": "6 “If the enema [<em>basti</em>] is given", "text": " after a full investigation&nbsp;of humors."}
    assert clean(v) == ("6", "“If the enema [basti] is given after a full investigation of humors.")
    assert clean({"verse_id": "8-14½", "text": " Thus declared  Atreya. "}) == ("8-14½", "Thus declared Atreya.")


def test_build_queries_one_clause_per_section_transcript_first_neutral_dropped():
    findings = {"nadi": {"pulse_rate": 64, "rhythm": "regular", "method": "manual", "dosha_observation": "kapha"},
                "jihva": {"coating": "white", "cracks": True, "swelling": False, "notes": ""},
                "mala": {"consistency": "formed", "bowel_pattern": "normal"},
                "agni": {"agni": "mandagni", "symptoms": ["bloating/gas", "low appetite"], "notes": "not assessed"}}
    transcripts = [{"speaker": "patient", "language": "hi", "raw_text": "...", "edited_text": None,
                    "translated_text": "I feel heavy after eating", "edited_translation": None}]
    assert build_queries(findings, transcripts) == [
        "patient says: I feel heavy after eating",
        "pulse: pulse rate 64, dosha observation kapha",
        "tongue: coating white, cracks",
        "appetite & digestion: agni mandagni, symptoms bloating/gas low appetite"]   # lone "stool: formed" dropped
    assert build_queries({}, []) == []
    assert build_queries({"sparsha": {"skin": "dry"}, "mala": {"notes": "straining"}}, []) == ["stool: notes straining"]


def test_red_flags():
    text = "patient says: My stomach hurts. My head is also hurting, and I have been vomiting for two days."
    assert red_flags({}, text) == ["vomiting for days", "vomiting with headache", "vomiting with abdominal pain"]
    assert red_flags({"drik": {"jaundice_flag": True}, "nadi": {"pulse_rate": 130}}, "") == ["jaundice", "pulse rate 130"]
    assert red_flags({"nadi": {"pulse_rate": 72}}, "patient says: I feel heavy after eating and have gas") == []
