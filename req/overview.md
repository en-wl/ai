# req — Generic LLM Query Package

`req` is a reusable Python package (`python -m req <model>`) that sends
structured data to LLMs via OpenRouter, parses markdown-table responses,
and stores results in SQLite.  It is configured entirely by a
`req-config.py` file in the working directory.

## Files

```
req/
  __main__.py           Request orchestration, response parsing, DB storage.
  schema.sql            Common schema (runs, requests, raw_data, errors, etc.).
  post.sql              Views loaded after task-local schema (results_w_model, cost views).
```

## Configuration

`req-config.py` is `exec()`'d into the package's namespace.  It can
override these defaults:

| Variable | Default | Purpose |
|---|---|---|
| `db` | `'data.db'` | SQLite database path |
| `system_prompt` | `'system_prompt.md'` | Path to system prompt file |
| `models_config` | *(built-in dict)* | Model definitions (config can override/extend) |
| `post_run` | `None` | Command to run between rounds, e.g. `['python3', 'populate_size_scores.py']` |
| `ENABLE_REDO` | `False` | Whether to retry failed UIDs |
| `temp_override` | `None` | Global temperature override |
| `key_file` | `'key.txt'` | Path to OpenRouter API key |
| `x_title` | *(required)* | Value for X-Title HTTP header |
| `http_referer` | `'https://github.com/en-wl/wordlist'` | Value for HTTP-Referer header |
| `input_rows(conn, model)` | candidates view query | Function returning input rows cursor (see below) |
| `validate_row(row, input_row)` | `None` | Optional validation/transformation callback |

## input_rows Contract

`input_rows(conn, model)` must return an iterable of rows whose columns
match the `input` table (as discovered by `PRAGMA table_info(input)`).
The first column must be `uid`.  Each row is sent to the LLM as a
pipe-delimited string, and the column values are also made available to
`validate_row` as a dict keyed by column name.

The default queries the `candidates` view, which requires a
`candidates.sql` (or equivalent) to be loaded into the database.

## Dynamic Column Discovery

At startup, column names and types are read from the database via
`PRAGMA table_info()`.  Columns `run_id` and `req_id` are treated as
internal; everything else in the `results` table is expected from the
LLM.  Type conversion is automatic: `INTEGER` columns attempt `int()`,
`REAL` columns attempt `float()`.

## How It Works

1. **Creates a `BatchSession`** that loads all uids a model still needs
   to evaluate (via the `candidates` view), shuffles them, and records a
   new run in the database.

2. **Dispatches batches concurrently** using a `ThreadPoolExecutor`
   (up to 100 workers).  Each batch sends a pipe-delimited table of
   input rows as the user message, with evaluation instructions as the
   system prompt, to the OpenRouter chat-completions API.

3. **Parses the LLM's markdown table** (`process_llm_response`).
   The parser detects header/separator lines, extracts cells, maps them
   to result columns, applies type conversion, and runs the optional
   `validate_row` callback.  Errors are collected for anything malformed.

4. **Stores everything** in SQLite — parsed `results` (row-by-row with
   graceful constraint-error handling), raw request/response JSON in
   `raw_data`, and parse `errors`.

5. **Handles failures gracefully:**
   - Rows that fail to parse or violate CHECK constraints are tracked and
     retried (when `ENABLE_REDO` is on) up to 3 times.
   - If fewer than 65% of expected rows come back valid, the entire
     batch is discarded and re-queued.
   - HTTP 429s are retried via urllib3's `Retry`; repeated 429s
     dynamically reduce the worker count.
   - Ctrl-C triggers a graceful shutdown that drains in-flight requests.

6. **Outer loop** — after each full pass, the `post_run` command (if set)
   is executed to refresh aggregated scores.  The loop exits when no new
   uids remain.

## Database Schema

Defined in `schema.sql`:

| Table | Purpose |
|---|---|
| `models` | Registered model aliases |
| `runs` | One row per evaluation run (model, temperature, etc.) |
| `requests` | One row per API call within a run |
| `raw_data` | Full JSON request/response for each API call |
| `errors` | Parse errors from malformed model output |

Defined in `post.sql` (loaded after the task-local schema, since
these views depend on the task-specific `results` table):

| View | Purpose |
|---|---|
| `results_w_model` | Results joined with run metadata (model name) |
| `request_cost` | Per-request cost extracted from raw API response |
| `uid_cost` | Per-request cost divided by output UIDs |
| `run_cost` | Aggregated cost per run |
| `runs_w_cost` | Runs table joined with cost data |
