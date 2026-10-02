"""Charaka Samhita verse retrieval: local bge-small embeddings, cosine search in pgvector.
Ingest once:  python -m app.rag data/charaka
# ponytail: exact scan, no index; add HNSW (vector_cosine_ops) if rows > ~100k or queries get slow.
"""
import html
import json
import re
import sys
import time
from functools import cache
from pathlib import Path

from sqlalchemy import func, literal_column, select, text as sql
from sqlalchemy.orm import Session

from app import db
from app.pariksha import ASSESSMENTS, SECTIONS

MODEL = "BAAI/bge-small-en-v1.5"
_TAG = re.compile(r"<[^>]+>")


@cache
def _model():
    from sentence_transformers import SentenceTransformer   # slow import; only when embedding is needed
    return SentenceTransformer(MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    return _model().encode(texts, normalize_embeddings=True, batch_size=64).tolist()


def clean(verse: dict) -> tuple[str, str]:
    """The scraper split on the first '<', so verse_id often holds 'id <start of text>'. Re-join, strip HTML."""
    vid, _, head = verse["verse_id"].strip().partition(" ")
    body = html.unescape(_TAG.sub("", f"{head} {verse['text']}"))
    return vid, re.sub(r"\s+", " ", body).strip()


def load(root: Path) -> list[db.Verse]:
    rows = []
    for f in sorted(root.rglob("*.json")):
        sthana = f.parent.name.split("(")[0].lstrip("0123456789.").strip()   # "1.Sutrasthana (Sutra ..." -> Sutrasthana
        chapter = f.stem.removeprefix("chapter")
        for v in json.loads(f.read_text(encoding="utf-8")):
            vid, body = clean(v)
            if body:
                rows.append(db.Verse(sthana=sthana, chapter=chapter, verse_id=vid, text=body))
    return rows


def ingest(root: Path) -> int:
    rows = load(root)
    for r, v in zip(rows, embed([f"{r.sthana}, Chapter {r.chapter}: {r.text}" for r in rows])):
        r.embedding = v
    with Session(db.engine) as s:
        s.execute(sql("CREATE EXTENSION IF NOT EXISTS vector"))
        db.Base.metadata.create_all(db.engine)
        s.execute(sql("ALTER TABLE verses ADD COLUMN IF NOT EXISTS tsv tsvector "
                      "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"))   # keyword half of search()
        s.execute(sql("CREATE INDEX IF NOT EXISTS ix_verses_tsv ON verses USING gin (tsv)"))
        s.query(db.Verse).delete()
        s.add_all(rows)
        s.commit()
    return len(rows)


QUERY_PREFIX = "Represent this sentence for searching relevant passages: "   # bge-en-v1.5 query-side instruction
NEUTRAL = {"normal", "regular", "moderate", "normal/formed", "once daily", "none", "mixed", "not assessed", ""}


def _keep(v) -> bool:
    return v not in (None, False, []) and not (isinstance(v, str) and v in NEUTRAL)


def build_queries(findings: dict, transcripts: list[dict]) -> list[str]:
    """One short English clause per Pariksha section plus one for the conversation. Neutral findings are dropped
    so 'rhythm regular, method manual' does not dilute the signal."""
    out = []
    for section, fields in findings.items():
        label = SECTIONS[section][0].split("·")[-1].strip()
        bits = [f.replace("_", " ") + ("" if v is True else f" {' '.join(v) if isinstance(v, list) else v}")
                for f, v in fields.items() if f != "method" and _keep(v)]
        # ponytail: a lone generic finding ("skin oily") costs a search and adds noise; assessments and notes always count
        if len(bits) >= 2 or section in ASSESSMENTS or fields.get("notes"):
            out.append(f"{label}: {', '.join(bits)}")
    said = [t["edited_translation"] or t["translated_text"] or (t["language"] == "en" and (t["edited_text"] or t["raw_text"]))
            for t in transcripts]
    if any(said):
        out.insert(0, "patient says: " + " ".join(x for x in said if x))
    return out


_WORD = re.compile(r"[a-z]{3,}")
_STOP = {"patient", "says", "also", "been", "feel", "feels", "feeling", "since", "days", "day", "week", "weeks", "two",
         "three", "four", "five", "very", "much", "lot", "well", "cannot", "get", "gets", "getting", "have", "has"}


def _keyword_hits(s: Session, clause: str, n: int) -> list[db.Verse]:
    """Postgres full-text, OR of the clause's words. The 1949 translation uses the same clinical words patients
    do (vomiting, stools, fever), which the embedding model under-weights: measured +3 hit@5 on 20 queries."""
    words = set(_WORD.findall(clause.split(":", 1)[-1].lower())) - _STOP
    if not words:
        return []
    tsq = func.to_tsquery("english", " | ".join(sorted(words)))
    tsv = literal_column("verses.tsv")   # stored generated column, see ingest()
    rank = func.ts_rank_cd(tsv, tsq, 1)   # normalisation 1: divide by log(doc length), so list-everything verses stop winning
    return list(s.scalars(select(db.Verse).where(tsv.op("@@")(tsq)).order_by(rank.desc()).limit(n)))


def search(s: Session, queries: list[str], k: int = 10) -> list[tuple[db.Verse, list[str]]]:
    """Reciprocal-rank fusion of one cosine search + one keyword search per clause, so a short transcript is not
    drowned by the form. The patient's own words count double. Returns (verse, [clause labels it matched])."""
    scores: dict[db.Verse, float] = {}
    matched: dict[db.Verse, list[str]] = {}
    for q, vec in zip(queries, embed([QUERY_PREFIX + q for q in queries])):
        label = q.split(":")[0]
        weight = 2 if label == "patient says" else 1
        dense = s.scalars(select(db.Verse).order_by(db.Verse.embedding.cosine_distance(vec)).limit(2 * k))
        for hits in (dense, _keyword_hits(s, q, 2 * k)):
            for rank, v in enumerate(hits):
                scores[v] = scores.get(v, 0) + weight / (60 + rank)
                if label not in matched.setdefault(v, []):
                    matched[v].append(label)
    return [(v, matched[v]) for v in sorted(scores, key=scores.get, reverse=True)[:k]]


if __name__ == "__main__":
    t0 = time.perf_counter()
    n = ingest(Path(sys.argv[1] if len(sys.argv) > 1 else "data/charaka"))
    print(f"ingested {n} verses in {time.perf_counter() - t0:.0f}s")
