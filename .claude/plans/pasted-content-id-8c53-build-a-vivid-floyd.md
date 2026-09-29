# Charaka Samhita RAG service (separate service in this repo)

## Context

The consultation app now captures transcripts, Ashtavidha Pariksha findings and two doctor-led
assessments. The next piece is a reference tool a licensed Ayurveda doctor can query against the
Charaka Samhita: semantic search over verse-level chunks, and a strict-RAG `/ask` that answers only
from retrieved passages with a citation on every point, and refuses when nothing relevant is found.
The user chose a **separate service** (own FastAPI app, own schema, own compose file) so the existing
consultation app and its host Postgres stay untouched.

## What inspection established (do not re-derive)

Dataset `github.com/gita/Datasets`, folder `Ayurveda/charak-samhita/`:
- 8 section folders named like `1.Sutrasthana (Sutra Sthana) — General Principles`, 142 `chapterN.json`
  files, 3.0 MB total.
- Every file is a JSON **list of `{"verse_id": str, "text": str}`**. No other keys anywhere (8,215 verses).
- **English only.** Zero Devanagari characters in the whole set. `sanskrit_text` will be NULL.
- `verse_id` is a messy string: `"1"`, `"4-5"`, `"8-14½"`, `"32-(2)"`, `"4-5.1"`, and a handful of
  scraper glitches where the id is a sentence fragment. Store raw; parse the first integer as `verse_start`.
- Verse length: median 208 chars, mean 271, p90 490, max 3,027 chars (~700 tokens). 3,819 verses are
  under 200 chars → **merging adjacent verses is the main path**; token-splitting is a rare fallback.
- Verse 1 of each chapter reads `We shall now expound the chapter entitled “<title>” …` → chapter title
  is extractable by regex.
- Repo has **no LICENSE file**; README says text was scraped from wisdomlib.org. Store
  `license = "unspecified (no LICENSE in source repo; scraped from wisdomlib.org)"`.
- The repo's own `Vectorise_Script/embedding.py` is an OpenAI ada-002 script for the Bhagavatam; not reusable.

Machine: no GPU, 12 cores, 14 GB RAM, Python 3.12 venv. Docker 29 works (`docker ps` OK) but the
`docker compose` plugin is **not installed** (`sudo apt install docker-compose-v2`). Host Postgres 17 has
no pgvector (pgvector is installed only for PG18, no PG18 cluster). Compose with `pgvector/pgvector:pg17`
avoids all of that. bge-m3 (568M params, 1024-dim, 8192 ctx) on CPU handles ~3,000 chunks in ~10–15 min.

## Layout (all new, under `rag/`)

```
rag/
  __init__.py
  settings.py         pydantic-settings: DATABASE_URL, EMBED_MODEL=BAAI/bge-m3, MIN_SIMILARITY=0.35,
                      TOP_K=6, ANTHROPIC_API_KEY, CLAUDE_MODEL=claude-opus-5, DATA_DIR=rag/data
  db.py               SQLAlchemy model `Chunk` + init(): CREATE EXTENSION vector, create_all, HNSW index
  embed.py            SentenceTransformer("BAAI/bge-m3") singleton; embed(texts) -> normalized float lists
  ingest.py           download (urllib, GitHub API) -> parse -> clean -> chunk -> embed -> upsert
  api.py              FastAPI: GET /health, POST /search, POST /ask
  eval.py             retrieval evaluation: precision/recall/F1/accuracy/MRR @5 and @8 + threshold check
  eval_questions.json ≥ 24 questions (20+ positives with expected chapters, 4 off-topic negatives)
  test_chunking.py    one pytest: chunk size bounds, source_id format, no verse lost (uses 2 fixture chapters)
  Dockerfile          python:3.12-slim, CPU torch, sentence-transformers, pgvector, anthropic, fastapi
  docker-compose.yml  db (pgvector/pgvector:pg17, port 5433) + api (port 8001), HF cache volume
  requirements.txt
  .env.example
  README.md
  data/               downloaded chapter JSONs (git-ignored)
```

Nothing under `app/` is touched. Ports 5433/8001 avoid the consultation app (5432/8000).

## Database schema (`rag/db.py`)

Table `charaka_chunks`:

| column          | type            | notes                                                   |
|-----------------|-----------------|---------------------------------------------------------|
| id              | serial PK       |                                                         |
| source_id       | text UNIQUE     | `CS.Su.1.4-5` = book.section-abbrev.chapter.verse-range |
| book            | text            | `Charaka Samhita`                                       |
| section         | text            | `Sutrasthana` … `Siddhisthana`                          |
| section_no      | int             | 1–8                                                     |
| chapter         | int             |                                                         |
| chapter_title   | text NULL       | from verse 1 regex                                      |
| verse           | text            | `4-5`, `8-14½`, or `4-5..17-17½` when verses were merged |
| verse_start     | int NULL        | first integer in the first verse_id                     |
| sanskrit_text   | text NULL       | always NULL for this source; column kept as required    |
| english_text    | text            | cleaned verse text(s) joined                            |
| chunk_text      | text            | context header + english_text (what gets embedded)      |
| source_url      | text            | github blob URL of the chapter file                     |
| license         | text            | see above                                               |
| topic_tags      | text[]          | keyword tags (see chunking)                             |
| embedding       | vector(1024)    | pgvector, normalized                                    |

`init()` runs `CREATE EXTENSION IF NOT EXISTS vector`, `Base.metadata.create_all`, then
`CREATE INDEX IF NOT EXISTS ... USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`.
Section abbreviations: Su, Ni, Vi, Sa, In, Ci, Ka, Si.

## Ingestion (`rag/ingest.py`)

1. **Download** (`--download`): list the tree via `api.github.com/repos/gita/Datasets/git/trees/main?recursive=1`,
   fetch each `Ayurveda/charak-samhita/**.json` raw file into `rag/data/<section_no>_chapterN.json`.
   Skip files already present.
2. **Parse**: section_no and section name from the folder name (`^(\d)\.(\w+)`), chapter from
   `chapter(\d+)`, verses in file order. Read `verse_id`/`text` only; fail loudly if a record lacks them
   (the plan's "do not assume field names" is satisfied by the inspection above plus this assertion).
3. **Clean**: collapse whitespace, `_` → space (scraper artifact like `its_true`), strip; skip verses
   whose cleaned text is empty. Chapter title = regex `entitled\s+[“‘"']?(.+?)[”’"']` on verse 1, else NULL.
4. **Chunk** (pure functions, unit-tested):
   - Walk verses in order, accumulate. Flush when the accumulated text ≥ 500 chars, or when adding the next
     verse would push it past 1200 and it is already ≥ 500. A lone verse > 1200 chars is its own chunk.
   - Fallback split: if a chunk exceeds 800 bge-m3 tokens (tokenizer from the model), split into
     ≤ 800-token windows with 150-token overlap; suffix source_id with `.p1`, `.p2`. Expected to fire
     rarely (max verse ≈ 700 tokens), but required.
   - `chunk_text` = `Charaka Samhita, {section} ({section_meaning}), Chapter {n}{ – title}, verses {range}:\n{english_text}`.
     The header is what makes "which chapter discusses X" queries retrievable.
   - `topic_tags`: match a ~60-term dictionary (dosha names, agni, dhatu, srotas, ama, jvara, prameha,
     kushtha, rasayana, vamana, basti, garbha, etc.) against the lowercased text.
     `# ponytail: keyword tags; swap for LLM tagging if tags ever drive retrieval`
5. **Embed**: `SentenceTransformer(EMBED_MODEL).encode(chunk_texts, batch_size=16, normalize_embeddings=True)`.
6. **Upsert** by `source_id` (INSERT … ON CONFLICT DO UPDATE) in batches of 200. Print counts:
   files, verses, chunks, chunk-length histogram, time.

Expected: ~2,600–3,000 chunks.

## API (`rag/api.py`)

- `POST /search` `{question, k=6}` (k clamped 5–8) → embed question (normalized) →
  `SELECT …, 1 - (embedding <=> :q) AS similarity … ORDER BY embedding <=> :q LIMIT :k`
  (`SET LOCAL hnsw.ef_search = 40`). Returns `[{source_id, section, chapter, chapter_title, verse,
  similarity, text}]`.
- `POST /ask` `{question, k=8}`:
  1. Retrieve as above, keep rows with `similarity ≥ MIN_SIMILARITY` (0.35, env-tunable).
  2. If none: `{"answer": "No sufficiently relevant Charaka Samhita passage was retrieved.", "points": [], "passages": []}`.
  3. Else call Claude via the `anthropic` SDK, model `claude-opus-5` (user did not name one; skill
     default), adaptive thinking left on, `output_config.effort="medium"`. Passages are given as
     numbered blocks tagged with their `source_id`. **Structured output** (`output_config.format`, pydantic
     schema) → `{"insufficient": bool, "points": [{"text": str, "citations": [source_id, ...]}]}`.
  4. System prompt (frozen, cached with `cache_control`): reference tool for licensed Ayurveda
     doctors; answer **only** from the supplied passages; every point must cite ≥ 1 source_id; set
     `insufficient=true` if the passages do not answer the question; **never** diagnose a patient,
     recommend/prescribe herbs, formulations, doses, or give patient-facing advice — if asked, say the
     tool cannot and point to the passages instead.
  5. Server-side enforcement (not trusting the model): drop any citation not in the retrieved set,
     drop any point left with zero citations; if `insufficient` or no points survive → the fixed
     "No sufficiently relevant…" message. Return `{answer (rendered "text [CS.Su.1.4-5]" lines), points,
     passages}`.
  6. Handle `stop_reason == "refusal"` and SDK errors → 502 with a readable message.
- `GET /health` → chunk count and model name.

Similarity threshold note: bge-m3 cosine between unrelated English texts often sits around 0.3–0.45,
so 0.35 is permissive. `eval.py` prints the top-1 similarity of the off-topic negatives so the user can
raise `MIN_SIMILARITY` with evidence.

## Evaluation (`rag/eval.py` + `rag/eval_questions.json`)

The user asked to score the **embedding model** on question embeddings with precision, recall, F1 and
accuracy. Ground truth is at **chapter level** (section + chapter), which can be labelled reliably from
the Charaka table of contents; verse-level labels would be guesswork.

- `eval_questions.json`: ≥ 20 positive questions, each with `expected: [[section_abbrev, chapter], …]`
  (one or more acceptable chapters) and ≥ 4 negatives with `expected: []` (e.g. paracetamol dosage,
  COVID guidance, Python code). Examples of positives: qualities of a good physician (Su 9), the four
  agni types (Vi 6), non-suppressible urges (Su 7), seasonal regimen (Su 6), fever pathology (Ni 1),
  prameha (Ni 4 / Ci 6), kushtha (Ni 5 / Ci 7), formation of the fetus (Sa 3 / Sa 4), monthly regimen in
  pregnancy (Sa 8), srotas (Vi 5), rasayana (Ci 1), vamana with madanaphala (Ka 1), basti (Si 1–3),
  vatavyadhi (Ci 28), tastes and incompatible foods (Su 26). Expected chapters are verified against the
  chapter titles in the downloaded data before the file is finalised.
- For each question: embed, retrieve top 8 from the DB, then at k=5 and k=8 compute
  - **precision@k** = relevant retrieved / k, **recall@k** = distinct expected chapters hit / expected,
    **F1@k**, **hit rate / accuracy** (≥ 1 relevant in top k; for negatives: correct iff top-1 similarity
    < MIN_SIMILARITY), **MRR**.
  - Report per-question rows and macro averages, plus the similarity distribution of positives vs
    negatives. Writes `rag/eval_results.json`, prints a table. Stdlib only (no sklearn).
- Comparing embedding models: `EMBED_MODEL=<other> python -m rag.ingest --table charaka_chunks_<name>`
  then `python -m rag.eval --table …`. Kept as a flag, not a framework.

## Docker

- `docker-compose.yml`: `db` = `pgvector/pgvector:pg17`, volume `pgdata`, healthcheck `pg_isready`,
  host port 5433. `api` = build `rag/Dockerfile`, depends on db healthy, env from `rag/.env`, volume
  `hf-cache:/root/.cache/huggingface` so the 2.2 GB model downloads once, port 8001, command
  `uvicorn rag.api:app --host 0.0.0.0 --port 8001`.
- Ingest: `docker compose -f rag/docker-compose.yml run --rm api python -m rag.ingest --download`.
- `Dockerfile`: `python:3.12-slim`, `pip install -r rag/requirements.txt` with torch from the CPU index
  (`--extra-index-url https://download.pytorch.org/whl/cpu`), copy `rag/`.
- Host-side alternative in README: use the venv against `localhost:5433` for faster iteration
  (same code, only `DATABASE_URL` differs).

## Requirements (`rag/requirements.txt`)

fastapi, uvicorn[standard], pydantic-settings, sqlalchemy, psycopg[binary], pgvector,
sentence-transformers, torch (CPU), anthropic, pytest.

## Safety constraints (requirement 12) — where they live

1. System prompt (never diagnose / prescribe / dose / patient-facing advice).
2. Server-side citation enforcement and the fixed refusal string (cannot be bypassed by the model).
3. README states the tool is for licensed Ayurveda doctors and is not medical advice.
4. `/ask` returns passages alongside points so the doctor reads the source, not just the summary.

## Steps

1. `settings.py`, `db.py`, `embed.py`, `requirements.txt`, compose + Dockerfile → verify: `docker compose up -d db`,
   `python -c "import rag.db; rag.db.init()"` creates the table and index (`\d charaka_chunks` shows the HNSW index).
2. `ingest.py` chunking functions + `test_chunking.py` → verify: pytest passes; chunk sizes 500–1200 chars
   except lone long verses; every verse appears in exactly one chunk.
3. Full ingest → verify: `/health` chunk count ≈ 2,600–3,000; spot-check `SELECT source_id, verse, length(chunk_text)`.
4. `api.py` `/search` → verify: "qualities of a good physician" returns Su 9 in the top 3.
5. `api.py` `/ask` → verify: a real question returns points each with ≥ 1 citation from the returned
   passages; "prescribe a dose of guggulu for my knee pain" gets a refusal to prescribe; "python list
   comprehension" returns the fixed no-passage message.
6. `eval_questions.json` (verify expected chapters against titles in the data) + `eval.py` → run, record
   baseline numbers in README.
7. README: setup, ingest, API examples, eval, limitations (English-only source, no license, threshold).

## Verification (end to end)

```bash
sudo apt install docker-compose-v2                       # one-time, user runs it
cp rag/.env.example rag/.env                             # add ANTHROPIC_API_KEY
docker compose -f rag/docker-compose.yml up -d db
docker compose -f rag/docker-compose.yml run --rm api python -m rag.ingest --download
docker compose -f rag/docker-compose.yml up -d api
curl -s localhost:8001/health
curl -s -X POST localhost:8001/search -H 'content-type: application/json' \
     -d '{"question": "What are the qualities of a good physician?"}' | jq '.[0:3]'
curl -s -X POST localhost:8001/ask -H 'content-type: application/json' \
     -d '{"question": "What does Charaka say about the four types of agni?"}'
docker compose -f rag/docker-compose.yml run --rm api python -m rag.eval
.venv/bin/python -m pytest rag/test_chunking.py -q
```

Success = ingest count in range, Su 9 in top 3 for the physician question, every `/ask` point cited,
negatives return the fixed message, eval prints metrics for ≥ 24 questions with hit rate@5 clearly
above chance, test passes.

## Assumptions (say so if wrong)

- LLM = Claude API, `claude-opus-5`, key via `ANTHROPIC_API_KEY`. Swapping to Sarvam chat later is a
  ~15-line change in one function.
- Relevance for evaluation is judged at chapter level.
- The 0.35 threshold is applied to cosine similarity of normalized bge-m3 vectors and is env-tunable.
- Ingestion downloads the data at run time; the 3 MB dataset is not committed.

## Deferred

- Hybrid BM25 + vector retrieval and a cross-encoder reranker (add if eval shows recall gaps).
- Sanskrit text from another source (wisdomlib has it; dataset does not).
- Linking `/search` to the consultation app's transcript + pariksha findings (query builder from the
  findings JSON, see the earlier RAG-readiness notes).
