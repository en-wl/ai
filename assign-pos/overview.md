# assign-pos: LLM-Assisted Part-of-Speech Assignment

## Purpose

Uses multiple LLMs (via the OpenRouter API) to assign correct parts of speech
(POS) to English words from a wordlist. The words come in with preliminary POS
guesses from automated heuristics, and the LLMs are asked to confirm or correct
each assignment.

## Input

~3,954 words stored in a SQLite database (`data.db`) via `test-input.sql`.
Each word has a UID and a preliminary POS guess:

- `n`: likely noun
- `v`: likely verb
- `m`: likely verb, possibly also a noun
- `a`: adjective or adverb
- `?`: unknown

The words range from proper nouns/names (Abbie, Adriano), to technical terms
(ATPase, ActiveX), to common words with ambiguous POS (water, record, object).
`test-extra.sql` adds a handful of particularly ambiguous words (e.g. "before",
"since", "both") for focused testing.

## How It Works

1. **`init.sh`** creates a fresh `data.db`, loads the shared schema
   (`../req/schema.sql`), the local schema (`schema-local.sql`), post-load
   views (`../req/post.sql`), and the input data.

2. **`system_prompt.md`** instructs the LLM to return a Markdown table with
   columns: `uid`, `word`, `lemma`, `pos`, `pos_class`, `notes`. Rules cover
   POS correction, when to flag `Wrong!` or `Obscure!`, and how to classify
   proper nouns into sub-classes (person, surname, place, demonym, etc.).

3. **`./req <model> [max_workers]`** (a wrapper around the shared `../req/`
   Python module) sends batched requests to LLMs. Each request contains a batch
   of words; the LLM returns a Markdown table which is parsed row by row.

4. **`req-config.py`** customizes the shared `req` framework for this task:
   - Defines a POS normalization map (e.g. "noun" -> "n", "adjective" -> "aj")
   - Sets valid `pos_class` values (person, surname, place, name, demonym, abbr, none)
   - Implements `validate_row()` which fixes malformed rows (wrong column count,
     duplicate columns, skipped lemma), checks for lemma mismatches via
     unidecode, and normalizes POS/pos_class values.

5. **Results** are stored in the `results` table keyed by `(uid, pos, pos_class,
   req_id)`. Multiple models and multiple runs produce multiple independent
   opinions per word.

## Models Used

Four models are used for this task: **qwen3-235b-a22b**, **grok-4.1-fast**,
**gpt-oss-120b**, and **llama-4-maverick**. qwen3 is the cheapest, so current
results contain 3 runs from qwen3 and 1 run each from the other three.
Reasoning is set to "none" for most models (overridden in `req-config.py`);
gpt-oss-120b uses "minimal".

## Analysis

- **`q.sql`**, **`q2.sql`** are scratch/ad-hoc query files used during analysis.
- **`candidates.sql`** appears to define which words still need more results
  from a given model.
- **`extract-resp.sh`** extracts raw LLM response text from the database for a
  given request ID.

## Cost Tracking

Views in `../req/post.sql` (`request_cost`, `uid_cost`, `run_cost`,
`runs_w_cost`, `model_costs`) track API costs per request, per UID, per run,
and per model.

## Database Schema

- **`input`**: (uid, word, pos) -- the words to classify
- **`results`**: (uid, run_id, req_id, word, lemma, pos, pos_class, notes) -- LLM outputs
- **`runs`**: metadata per batch run (model, batch_size, temperature, etc.)
- **`requests`**: per-request metadata (timing, errors)
- **`raw_data`**: raw JSON request/response pairs
- **`errors`**: validation errors from response parsing

## Key Files

| File | Purpose |
|---|---|
| `init.sh` | Initialize fresh database |
| `system_prompt.md` | LLM instructions for POS assignment |
| `req-config.py` | Task-specific config: validation, POS maps |
| `test-input.sql` | ~3,954 input words |
| `test-extra.sql` | Extra ambiguous test words |
| `schema-local.sql` | Task-specific tables (input, results) |
| `q*.sql` | Scratch/ad-hoc analysis queries |
| `candidates.sql` | Candidate selection for re-runs |
| `extract-resp.sh` | Extract raw response for a request |
| `req` | Shell wrapper to run the req module |
| `../req/` | Shared request framework (batching, API calls, parsing) |
