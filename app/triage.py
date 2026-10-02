"""Keyword screen for red flags that need urgent medical assessment before any Ayurvedic interpretation.
Not a diagnosis: it only flags, the doctor decides. Runs on the English transcript + Pariksha findings.
# ponytail: regex rules; swap for an LLM classifier only once there is a reviewed case set to measure it on."""
import re


def red_flags(findings: dict, text: str) -> list[str]:
    t = text.lower()
    has = lambda rx: re.search(rx, t) is not None   # noqa: E731
    vomit = has(r"vomit|throw(ing|n)? up")
    flags = []
    if vomit and has(r"(\d|two|three|four|five|several|many|whole|all) days?"):
        flags.append("vomiting for days")
    if vomit and has(r"head ?ache|head\b.{0,15}(hurt|pain|ach)"):
        flags.append("vomiting with headache")
    if vomit and has(r"(stomach|abdom|belly|tummy)\b.{0,20}(hurt|pain|ach)"):
        flags.append("vomiting with abdominal pain")
    if has(r"\bblood|bleed|black stool|tarry"):
        flags.append("bleeding mentioned")
    if has(r"chest pain|breathless|short(ness)? of breath|difficult\w* breath|can'?t breathe"):
        flags.append("chest pain or breathlessness")
    if has(r"(severe|worst|sudden|unbearable) head ?ache|stiff neck|blurred vision|double vision"):
        flags.append("severe headache or neurological sign")
    if has(r"faint|unconscious|confus|seizure|convuls|\bfits?\b"):
        flags.append("fainting, confusion or seizure")
    if has(r"pregnan"):
        flags.append("pregnancy mentioned")

    g = lambda s, f: findings.get(s, {}).get(f)   # noqa: E731
    if g("drik", "jaundice_flag"):
        flags.append("jaundice")
    if g("drik", "pallor_flag"):
        flags.append("marked pallor")
    if g("mala", "blood") or "blood reported" in (g("mala_assessment", "concerns") or []):
        flags.append("blood in stool")
    if g("shabda", "breathless_while_speaking"):
        flags.append("breathless while speaking")
    if g("nadi", "rhythm") == "irregularly irregular":
        flags.append("irregularly irregular pulse")
    if (r := g("nadi", "pulse_rate")) and not 45 <= r <= 120:
        flags.append(f"pulse rate {r}")
    if g("sparsha", "temperature") == "hot":
        flags.append("high temperature")
    if g("mutra", "colour") == "red":
        flags.append("red urine")
    return flags
