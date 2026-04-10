# assign-pos: LLM-Assisted Part-of-Speech Assignment

## Purpose

Uses multiple LLMs (via the OpenRouter API) to assign correct parts of speech
(POS) to English words from a wordlist.  The words come in with preliminary
POS guesses from automated heuristics, and the LLMs are asked to confirm or
correct each assignment, optionally tagging proper-noun sub-classes,
abbreviations, fragments, obscure senses, and outright wrong tags.

## Input

~3,954 words stored in a SQLite database (`data.db`) via `test-input.sql`.
Each word has a UID and a preliminary POS guess:

- `n`: likely noun (including proper-noun)
- `v`: likely verb
- `m`: likely verb, possibly also a noun
- `a`: adjective or adverb
- `?`: unknown

The words range from proper nouns/names (Abbie, Adriano), to technical terms
(ATPase, ActiveX), to common words with ambiguous POS (water, record,
object).  `test-extra.sql` adds a handful of particularly ambiguous words
(e.g. "before", "since", "both") for focused testing.

## How It Works

1. **`init.sh`** creates a fresh `data.db`, loads the shared schema
   (`../req/schema.sql`), the local schema (`schema-local.sql`), post-load
   views (`../req/post.sql`), and the input data
   (`test-input.sql` + `test-extra.sql`).

2. **`system_prompt.md`** instructs the LLM to return a Markdown table with
   columns: `uid`, `word`, `lemma`, `pos`, `pos_class`, `notes`.  Rules cover
   POS correction, when to flag `Wrong!`, `Obscure!`, and `Fragment.`, and
   how to classify proper nouns into sub-classes (person, surname, place,
   demonym, name, acronym).

3. **`./req <model> [max_workers]`** (a tiny shell wrapper around
   `python -m req`) sends batched requests to LLMs.  Each request contains a
   batch of words; the LLM returns a Markdown table which is parsed
   row-by-row by the shared `req` framework.

4. **`./req-all`** runs the standard fleet of models in dynamic mode:
   `qwen3-235b-a22b qwen3-235b-a22b gpt-oss-120b grok-4.1-fast
   llama-4-maverick gemma-4-31b` (qwen runs twice because it is the cheapest
   and contributes more samples).  `REQ_MODE=DYNAMIC` is exported here.

5. **`req-config.py`** customizes the shared `req` framework for this task:
   - Requires `REQ_MODE` env var (`ONCE` or `DYNAMIC`).
   - Forces `reasoning="none"` for every model except `gpt-oss-120b` (which
     uses `"low"`).
   - Defines a POS normalization map (e.g. "noun" → "n", "adjective" → "aj")
     and the set of valid `pos_class` values
     (person, surname, place, name, demonym, abbr, none).
   - Implements `validate_row()`, which fixes malformed rows (wrong column
     count, duplicate columns, skipped lemma, orig pos returned after word),
     checks word/lemma compatibility via `unidecode`, normalizes POS and
     `pos_class`, and folds `name/person/surname` POS strings into POS `n`.
   - In `ONCE` mode: `ENABLE_REDO=True`, `input_rows` returns the full input
     table.
   - In `DYNAMIC` mode: `DYNAMIC_MODE=True`, `CROSS_MODEL_DEPS=True`,
     `create_candidates_temp_table()` runs `candidates-dynamic.sql.in`, and
     `on_request_complete()` calls `combine.update_uid()` for every uid in
     `completed_reqs` then refreshes the per-uid count tables.
   - Wires `pre_run` and `post_run` to `combine.py` so the derived tables
     are rebuilt before and after every invocation.

6. **`combine.py`** post-processes raw `results` into normalized
   `adj_results_by_model` / `adj_results` and the count tables
   (`pos_class_cnts[_by_model]`, `pos_cnts[_by_model]`,
   `class_cnts[_by_model]`, `lemma_cnts[_by_model]`).  Normalization rules
   include:
   - `should_filter()` drops `pos=''` rows and `Wrong!`-but-input-consistent
     rows.
   - `Fragment.` rows are duplicated under `pos='wp'` (word-part).
   - `apply_normalization()` folds `abbr/abbr → abbr/''`, collapses
     `pos='abbr'` to a unique candidate POS when one exists, prefers
     `surname` over `person` on ties, folds `pos_class='name'` into a unique
     specific subtype, and merges empty `pos_class` into a unique non-empty
     one when supported by enough samples.
   - `update_combined_data()` re-applies the normalization across models so
     the cross-model `adj_results` reflects model-weighted counts.
   - When invoked as a script, it rebuilds everything from scratch
     (`combine-init.sql` drops & recreates the tables).
   - `combine-config.py` (optional, not checked in) can override
     `FINAL_MODELS` to restrict the cross-model view to a specific model set.

7. **Results storage** — `results_all` is the underlying table keyed by
   `(uid, pos, pos_class, req_id)` with an `exclude` column for soft
   deletion; `results` is a view filtering out excluded rows, with an
   `INSTEAD OF INSERT` trigger so the `req` framework can keep writing to
   `results` transparently.  Multiple models and multiple runs produce
   multiple independent opinions per word.

## Models Used

The default fleet (set by `req-all`) is **qwen3-235b-a22b** (×2 for cost
reasons), **gpt-oss-120b**, **grok-4.1-fast**, **llama-4-maverick**, and
**gemma-4-31b**.  Reasoning is forced to `none` for all of them except
`gpt-oss-120b`, which uses `low`.

## Candidate Selection

Two SQL templates pick which uids still need work:

- **`candidates.sql.in`** (used in `ONCE` mode via the default
  `input_rows`-style query): pulls uids from the persistent `combined` /
  `combined_w_model` summaries.
- **`candidates-dynamic.sql.in`** (used in `DYNAMIC` mode by
  `create_candidates_temp_table`): same logic but reads from the
  `pos_class_cnts[_by_model]` tables produced by `combine.py`.

Both templates apply the same tier rules: ensure ≥3 qwen3 samples, ≥1 sample
from every other model, escalate to ≥5 samples per model and ≥3 cross-model
samples whenever a uid still has unresolved or `Obscure!` buckets.

`candidates2.sql.in` is an older variant kept around for ad-hoc inspection.

## Analysis

- **`q.sql`**, **`q2.sql`** are scratch/ad-hoc query files used during
  analysis.
- **`extract-resp.sh <req_id>`** extracts the raw LLM response text from
  `raw_data` for a given request id.

## Cost Tracking

Views in `../req/post.sql` (`request_cost`, `uid_cost`, `run_cost`,
`runs_w_cost`, `model_costs`) track API costs per request, per UID, per run,
and per model.

## Database Schema

Tables defined in `schema-local.sql`:

- **`input`** `(uid, word, pos)` — the words to classify.
- **`results_all`** `(row_id, uid, run_id, req_id, word, lemma, pos,
  pos_class, notes, exclude)` — every parsed LLM row.  `exclude` lets a row
  be soft-deleted without losing it.
- **`results`** — view over `results_all where exclude is null`, with an
  `INSTEAD OF INSERT` trigger so writes from `req` go straight into
  `results_all`.
- An `index results_run_id` on `(run_id, uid, req_id) where exclude is null`
  keeps the candidate query fast.

Tables defined in `combine-init.sql` (rebuilt by `combine.py`):

- **`adj_results_by_model`** / **`adj_results`** — per-row normalized POS /
  pos_class for the by-model and cross-model views.  `pos`/`pos_class` are
  NULL for filtered rows so totals still reflect the actual sample count.
- **`pos_class_cnts_by_model`**, **`pos_cnts_by_model`**,
  **`class_cnts_by_model`**, **`lemma_cnts_by_model`** — per-(uid, model)
  counts.
- **`pos_class_cnts`**, **`pos_cnts`**, **`class_cnts`**, **`lemma_cnts`** —
  cross-model counts with both raw `cnt` (number of models in agreement) and
  weighted `cnt_w` (sum of fractional agreement).

Tables defined in `../req/schema.sql` (see `req/overview.md`): `models`,
`runs`, `requests`, `raw_data`, `errors`, plus the dynamic-mode coordination
tables `outstanding_runs`, `outstanding_reqs`, `completed_reqs`,
`skipped_uids`.

## Key Files

| File | Purpose |
|---|---|
| `init.sh` | Initialize fresh `data.db` |
| `system_prompt.md` | LLM instructions for POS assignment |
| `req-config.py` | Task-specific config: validation, POS maps, mode handling |
| `combine.py` | Post-processing into normalized count tables |
| `combine-init.sql` | Schema for the tables `combine.py` produces |
| `test-input.sql` | ~3,954 input words |
| `test-extra.sql` | Extra ambiguous test words |
| `schema-local.sql` | Task-specific tables (input, results_all + view) |
| `candidates.sql.in` | Candidate query for ONCE mode |
| `candidates-dynamic.sql.in` | Candidate query for DYNAMIC mode |
| `candidates2.sql.in` | Older variant kept for ad-hoc use |
| `q.sql`, `q2.sql` | Scratch/ad-hoc analysis queries |
| `extract-resp.sh` | Extract raw response for a given req_id |
| `req` | Shell wrapper that runs `python -m req` with PYTHONPATH set |
| `req-all` | Wrapper that runs the standard model fleet in DYNAMIC mode |
| `../req/` | Shared request framework (batching, API calls, parsing) |
