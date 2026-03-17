# Ask-LLM: Overview

This project uses an ensemble of LLM models to evaluate English lemmas
for inclusion and sizing in a spell-checker wordlist.  The central
question for each lemma is: should it be in the wordlist, and if so,
at what size tier?

## Size Categories

- **60** — Mainstream words any educated user expects a spell checker to
  accept (e.g. "emoji", "YouTube", "blockchain").
- **70** — Valid but specialized or less routine; dictionary-attested but
  not everyday (e.g. "tokenization", "proteobacterium").
- **80** — Passes inclusion but cannot be justified at 60 or 70.
- **99 (Excluded)** — Not suitable for the wordlist at all (misspellings,
  transient slang, extremely obscure terms).

Borderline flags (`60/70`, `70/80`, `incl/excl`) capture cases where the
model is uncertain between adjacent tiers.

## Input

466 lemmas live in the `input` table (loaded from `input-data.sql`).
Each has a uid, one or more comma-separated lemma forms, and a base
part of speech.  Examples span common words, brand names, abbreviations,
scientific terms, slang, chemical elements, and currency codes.

## Pipeline

```
init.sh          Set up data.db: schema, input data, views.
       ↓
req.py           Send batches of lemmas to LLMs via OpenRouter,
                 parse markdown-table responses, store results.
       ↓
populate_size_scores.py
                 Aggregate per-model votes into model_size_scores,
                 then run the ensemble to populate final_size_scores.
       ↓
candidates view  Identify lemmas that still need more model evaluations.
       ↓
(repeat)         req.py loops: populate scores → send next round →
                 until every lemma has enough confident coverage.
```

### req.py — Request orchestration

`req.py` is the main driver.  It:

1. **Reads the model config** — a dictionary of ~8 models (GPT-5.2,
   Gemini 2.5 Flash, DeepSeek v3.2, Llama 4 Maverick, Qwen variants,
   etc.) with provider routing, batch sizes, temperature, reasoning
   effort, and optional stop sequences.

2. **Creates a `BatchSession`** that loads all uids a model still needs
   to evaluate (via the `candidates` view), shuffles them, and records a
   new run in the database.

3. **Dispatches batches concurrently** using a `ThreadPoolExecutor`
   (up to 100 workers).  Each batch sends a table of `uid|lemmas|base_pos`
   rows as the user message, with the evaluation instructions as the
   system prompt, to the OpenRouter chat-completions API.

4. **Parses the LLM's markdown table** (`process_llm_response`).
   The parser detects header/separator lines, extracts uid, lemma, POS,
   size, borderline flag, and notes from each data row.  It validates
   uids, lemma matches (via Unicode-normalized comparison), size values,
   and borderline strings, collecting errors for anything malformed.

5. **Stores everything** in SQLite — the parsed `results`, raw
   request/response JSON in `raw_data`, and any parse `errors`.

6. **Handles failures gracefully:**
   - Rows that failed to parse are tracked in `failed_uids` and retried
     (when `ENABLE_REDO` is on) up to 3 times.
   - If fewer than 65 % of expected rows come back valid, the entire
     batch is discarded and re-queued.
   - HTTP 429s are retried via urllib3's `Retry`; repeated 429s
     dynamically reduce the worker count.
   - Ctrl-C triggers a graceful shutdown that drains in-flight requests.

7. **Outer loop** — after each full pass, `populate_size_scores.py` is
   re-run (via subprocess) to refresh aggregated scores and the
   candidates view.  The loop exits when no new uids remain.

### populate_size_scores.py — Score aggregation

Reads `results_w_model` (results joined with run metadata) and, for
each (uid, model) pair:

- Converts borderline votes: 2/3 weight to the winning side, 1/3 to
  the losing side.
- Picks the model's chosen size via an upper-median of the weighted
  distribution.
- Writes per-model mass allocations (`s_60`, `s_70`, `s_80`, `s_99`)
  and upper/lower bounds to `model_size_scores`.
- Calls `determine_final_size()` from `size_decider.py` to compute the
  ensemble decision and writes it to `final_size_scores`.

### size_decider.py — Ensemble voting

A three-stage decision process using weighted votes from all models:

1. **Exclusion (size 99).**
   If GPT-5.2 puts ≥ 2/3 of its mass on 99 the lemma is excluded.
   DeepSeek can also exclude if ≥ 4/5 mass on 99 *and* corroborated by
   at least one other model.

2. **Size 60 decision.**
   GPT-5.2 has veto power: if it assigns zero mass to 60 the lemma
   cannot be 60.  Otherwise a weighted score
   `Σ weight × (mass_60 − mass_70+)` is computed; if it meets the 60 %
   threshold the lemma is size 60.

3. **Size 70 vs 80.**
   A similar weighted score `Σ weight × (mass_60 + mass_70)` decides
   between 70 and 80 at a 60 % threshold.

All arithmetic uses exact rational fractions (`fracs.py`) to avoid
floating-point rounding issues.

## Database Schema (key tables)

| Table | Purpose |
|---|---|
| `input` | 466 lemmas to evaluate (uid, lemmas, base_pos) |
| `models` | Registered model aliases |
| `runs` | One row per evaluation run (model, temperature, etc.) |
| `requests` | One row per API call within a run |
| `raw_data` | Full JSON request/response for each API call |
| `results` | Parsed model judgments (uid, size, borderline, notes) |
| `errors` | Parse errors from malformed model output |
| `model_size_scores` | Aggregated per-model mass distributions |
| `final_size_scores` | Ensemble decision for each lemma |

Views: `candidates` (lemmas needing more evals), `results_w_model`,
and cost-tracking views (`request_cost`, `run_cost`, etc.).

## Configuration

- **API key** — `key.txt` (OpenRouter bearer token).
- **Model configs** — `models_config` dict in `req.py`: model name,
  provider routing, batch size, temperature, reasoning effort,
  max output tokens, optional stop sequence.
- **System prompt** — `system_prompt.md`, generated by `system_prompt.sh`,
  contains detailed inclusion/exclusion criteria and size-tier
  definitions the LLMs follow.
- **Thresholds** — hardcoded in `size_decider.py` (60 % for both
  stage-2 and stage-3 decisions).

## Supporting Files

- `fracs.py` — Lightweight exact-fraction library (`Frac` class) used
  by `size_decider.py` for precise weighted arithmetic.
- `init.sh` — One-time setup: creates `data.db`, applies schema, loads
  input data, creates views.
- `sqliterc.sql` — SQLite pragmas (WAL mode, foreign keys, busy timeout).
