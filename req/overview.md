# req — Generic LLM Query Package

`req` is a reusable Python package (`python -m req <model> [model2 ...] [max_workers] [batch_size]`)
that sends structured data to LLMs via OpenRouter, parses markdown-table
responses, and stores results in SQLite.  It is configured entirely by a
`req-config.py` file in the working directory.

## Files

```
req/
  __main__.py           Entry point + per-model BatchSession loop.
  _config.py            Config loading, DB helpers, model registry,
                        dynamic column discovery from `input`/`results`.
  _request.py           HTTP/streaming, response parsing, results storage.
  _manager.py           Multi-model orchestrator: spawns one --managed child
                        per model, 3-stage signal escalation, run_id assignment,
                        outstanding_runs/_reqs cleanup, pre_run/post_run hooks.
  schema.sql            Common schema (runs, requests, raw_data, errors,
                        outstanding_runs, outstanding_reqs, completed_reqs,
                        skipped_uids, models).
  post.sql              Views loaded after task-local schema (results_w_model,
                        errors_w_model, cost views).
```

## Invocation

```
python -m req <model> [model2 ...] [max_workers] [batch_size]
```

When more than one model is given, `_manager.run()` spawns one child process
per model (each re-invoking `python -m req --managed <run_id> <model>`) and
forwards stdout/stderr to the parent with a `[pid]` prefix.  A single-model
invocation also goes through the manager so signal handling and run-id
allocation are uniform.

## Configuration

`req-config.py` is `exec()`'d into the package's namespace.  It can override
these defaults:

| Variable | Default | Purpose |
|---|---|---|
| `db_file` | `'data.db'` | SQLite database path |
| `system_prompt` | `'system_prompt.md'` | Path to system prompt file |
| `models_config` | *(built-in dict)* | Model definitions (config can override/extend) |
| `ENABLE_REDO` | `False` | Whether to retry failed UIDs (not allowed with `DYNAMIC_MODE`) |
| `DYNAMIC_MODE` | `False` | Use per-batch candidate selection instead of one upfront list |
| `CROSS_MODEL_DEPS` | `False` | In dynamic mode, coordinate runs through `outstanding_runs` state machine so a model can wait on others before re-checking |
| `STALE_RUNS_TIMEOUT` | `600` | Seconds before stale `outstanding_runs` rows are cleaned up at startup |
| `temp_override` | `None` | Global temperature override |
| `key_file` | `'key.txt'` | Path to OpenRouter API key (env `REQ_KEY_FILE` wins) |
| `x_title` | *(required)* | Value for X-Title HTTP header |
| `http_referer` | `'https://github.com/en-wl/wordlist'` | Value for HTTP-Referer header |
| `input_rows(conn, model)` | `select * from input where uid in (select uid from candidates where model = ?)` | Iterable of rows to send (see below) |
| `validate_row(row, input_row)` | `None` | Optional validation/transformation callback returning `(row, err_or_None)` |
| `create_candidates_temp_table(conn, model, run_id)` | `None` | Dynamic-mode callback that populates a `_candidates` temp table |
| `on_request_complete()` | `None` | Dynamic-mode callback fired after each request finishes; opens its own DB connection |
| `pre_run` / `post_run` | `None` | Argv list for a subprocess to run once before children start / after they finish |

## input_rows Contract

`input_rows(conn, model)` must return an iterable of rows whose columns match
the `input` table (as discovered by `PRAGMA table_info(input)`).  The first
column must be `uid`.  Each row is sent to the LLM as a pipe-delimited string,
and the column values are also made available to `validate_row` as a dict
keyed by column name.

## Dynamic Column Discovery

At startup, column names and types are read from the database via
`PRAGMA table_info()`.  Columns `run_id` and `req_id` are treated as internal;
everything else in the `results` table is expected from the LLM.  Type
conversion is automatic: `INTEGER` columns attempt `int()`, `REAL` columns
attempt `float()`.  A `Row` class is dynamically constructed so that
`validate_row` can access fields by name.

## How It Works

1. **`_manager.run()`** allocates `run_id`s, cleans up stale `outstanding_runs`
   from prior crashed invocations, runs `pre_run` if defined, then forks one
   child per model with the `--managed <run_id>` flag.  Each child eventually
   calls `main()` which constructs a `BatchSession`.

2. **`BatchSession`** loads the uids the model still needs to evaluate (via
   `input_rows`), shuffles them, and records a new row in `runs`.  In
   `DYNAMIC_MODE` it doesn't preload uids — it defers to
   `create_candidates_temp_table()` on each batch.

3. **`main()` dispatches batches concurrently** using a `ThreadPoolExecutor`
   (up to 100 workers).  Each batch sends a pipe-delimited table of input rows
   as the user message and `instructions` (with optional model-specific
   `special` text appended) as the system prompt to the OpenRouter
   chat-completions API.  Streaming responses are reassembled into a single
   message object before parsing.

4. **`process_llm_response()`** parses the LLM's markdown table.  The parser
   detects header/separator lines, splits cells, drops duplicates, validates
   the UID is one we asked for, runs the optional `validate_row` callback,
   enforces column count, applies type conversion, and collects errors for
   anything malformed.

5. **`store_parse_result()`** writes parsed `results` row-by-row.  Constraint
   violations are caught individually so one bad row doesn't lose the rest of
   the batch; offending rows are deleted and recorded in `errors`.

6. **Failure handling:**
   - Per-UID failure counts are tracked across requests; after 3 consecutive
     failures a UID is added to `bad_uids` and skipped.  In dynamic mode the
     skip is also persisted to `skipped_uids`.
   - If `good_rows < 2 * bad_rows` (or `good_rows == 0`), the entire batch's
     parsed rows are discarded and re-queued.
   - HTTP 429s are retried via urllib3's `Retry`; repeated 429s or repeated
     connection errors trigger exponential backoff (`error_delay` doubles up
     to 30s).
   - Five consecutive `other`-class errors enter "failure mode" shutdown.
   - SIGINT triggers a graceful shutdown that drains in-flight requests and
     exits with code 1; the manager escalates SIGINT → SIGTERM → SIGKILL on
     repeated presses.

7. **Dynamic mode (`DYNAMIC_MODE = True`)** — candidates are queried each
   batch via `create_candidates_temp_table()`, and `on_request_complete()` is
   called after each request to incrementally update derived tables.  When
   `CROSS_MODEL_DEPS` is also set, the `outstanding_runs` table is used as a
   simple state machine (`active` / `waiting` / `wakeup` / `done`) so a run
   can wait for sibling runs to publish more results before deciding it's
   actually done.

8. **Manager wrap-up** — child exit codes are collected, `outstanding_runs`
   /`outstanding_reqs` rows for each finished run are cleared, the highest
   exit code wins, `post_run` is invoked if all children succeeded, and the
   journal mode is reset to `delete` so the resulting `data.db` is easy to
   move around.

## Database Schema

Defined in `schema.sql`:

| Table | Purpose |
|---|---|
| `models` | Registered model aliases |
| `runs` | One row per evaluation run (model, batch_size, temperature, reasoning_effort, sample_type) |
| `requests` | One row per API call (entry_time, send_time, run_id, batch_size, error, model_notes) |
| `raw_data` | Full JSON request/response for each API call |
| `errors` | Parse / validation / constraint errors |
| `outstanding_runs` | Coordination state for in-flight runs (dynamic mode) |
| `outstanding_reqs` | In-flight per-uid requests (dynamic mode) |
| `completed_reqs` | UIDs whose request has just landed and the post-request callback hasn't yet observed (dynamic mode) |
| `skipped_uids` | UIDs that have been declared bad for a given run |

The task-local `schema-local.sql` is expected to define `input` and `results`
(and any additional task-specific objects).

Defined in `post.sql` (loaded after the task-local schema, since these views
depend on the task-specific `results` table):

| View | Purpose |
|---|---|
| `results_w_model` | Results joined with run metadata (model name) |
| `errors_w_model` | Errors joined with run metadata |
| `request_cost` | Per-request cost extracted from raw API response |
| `uid_cost` | `request_cost` divided by output uid count |
| `run_cost` | Aggregated cost per run |
| `runs_w_cost` | Runs joined with cost data |
| `model_costs` | Total cost / total uids / per-uid cost grouped by model |
