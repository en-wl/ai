import os
import sqlite3
import threading
from  contextlib import contextmanager
from pathlib import Path

# === Configurable defaults (can be overridden by req-config.py) ===

db_file = 'data.db'

system_prompt = 'system_prompt.md'
validate_row = None

ENABLE_REDO = False

DYNAMIC_MODE = False
CROSS_MODEL_DEPS = False
STALE_RUNS_TIMEOUT = 600               # seconds before outstanding_runs deemed stale
on_request_complete = None             # callback() — no params, opens DB itself
create_candidates_temp_table = None    # callback(conn, model, run_id)

pre_run = None     # list of args for subprocess (run once before children start)
post_run = None    # list of args for subprocess (run once after children finish)

key_file = 'key.txt'
x_title = None  # required — config must set this
http_referer = 'https://github.com/en-wl/wordlist'

def input_rows(conn, model):
    return conn.execute("select * from input where uid in (select uid from candidates where model = ?)",
                       (model,))

temp_override = None # Model temp. override

models_config = {
    # "claude-sonnet-4.5": {
    #     "name": "anthropic/claude-sonnet-4.5",
    #     "providers": ["anthropic", "google-vertex"],
    #     "reasoning": "low",
    #     "batch_size": 500,
    # },
    "gpt-5.2": {
        "name": "openai/gpt-5.2",
        "providers": ["openai"],
        "reasoning": "low",
        "batch_size": 350, # 400
    },
    "gpt-5.3-chat": {
        "name": "openai/gpt-5.3-chat",
        "providers": ["openai"],
        "batch_size": 200,
    },
    "gpt-5.4-nano": {
        "name": "openai/gpt-5.4-nano",
        "providers": ["openai"],
        "batch_size": 200,
    },
    "gpt-oss-120b": {
        "name": "openai/gpt-oss-120b",
        "providers": ["deepinfra/bf16"], # [], # "chutes/bf16"
        "reasoning": "medium",
        "batch_size": 100,
    },
    "gemini-2.5-flash": {
        "name": "google/gemini-2.5-flash",
        "providers": ["google-vertex"],
        "reasoning": "low",
        "batch_size": 200,
        "stop": "<<<END>>>",
        "special": "After the Notes section, output the exact text `<<<END>>>` on its own line, then stop.",
    },
    "gemma-4-31b": {
        "name": "google/gemma-4-31b-it",
        "providers": ["parasail/bf16", "akashml/bf16", "venice/bf16"],
        "reasoning": "low",
        "batch_size": 100,
    },
    "grok-4.1-fast": {
        "name": "x-ai/grok-4.1-fast",
        "providers": ["xai"],
        "reasoning": "low",
        "batch_size": 200,
    },
    "deepseek-v3.2": {
        "name": "deepseek/deepseek-v3.2",
        "providers": ["novita/fp8","siliconflow/fp8","atlas-cloud/fp8"],
        "reasoning": "low",
        "batch_size": 80,
    },
    # "llama-3.3-70b": {
    #     "name": "meta-llama/llama-3.3-70b-instruct",
    #     "providers": ["novita/bf16","crusoe/bf16"],
    #     "batch_size": 100,
    # },
    "llama-4-maverick": {
        "name": "meta-llama/llama-4-maverick",
        "providers": ["deepinfra/base"], #  "parasail/fp8"],
        "batch_size": 100,
    },
    "llama-4-scout": {
        "name": "meta-llama/llama-4-scout",
        "providers": ["novita/bf16"],
        "batch_size": 100,
    },
    "qwen3-235b-a22b": {
        "name": "qwen/qwen3-235b-a22b-2507",
        "providers": ["wandb/bf16"], # ["crusoe/bf16"]
        "batch_size": 100,
        "max_output": 9000,
        "temperature": 0.7,
        "top_p": 0.8,
    },
    "qwen3.5-397b-a17b": {
        "name": "qwen/qwen3.5-397b-a17b",
        "providers": ["parasail/fp8", "novita/fp8"], # "atlas-cloud/fp8"],
        "reasoning": "none",
        "batch_size": 100,
        "max_output": 9000,
        "temperature": 0.7,
        "top_p": 0.8,
        "presence_penalty" : 1.5,
        "top_k": 20,
    },
    # "qwen3-235b-a22b-thinking": {
    #     "name": "qwen/qwen3-235b-a22b-thinking-2507",
    #     "providers": ["deepinfra/fp8", "novita/fp8", "atlas-cloud/fp8"],
    #     "reasoning": "minimal",
    #     "batch_size": 35,
    #     "max_output": 32000,
    # }
}

# === helper function ===

SLOW_QUERY_THRESHOLD = 0.2

@contextmanager
def open_db(mode='r', desc = None, timeout = 5000):
    if desc is None:
        desc = 'unknown'
    import sqlite3
    if mode not in ('r', 'w', None):
        raise ValueError
    if not os.path.exists(db_file):
        raise FileNotFoundError(f"Database not found: {db_file}")
    if mode == 'r':
        conn = sqlite3.connect(f'file:{db_file}?mode=ro', uri=True, isolation_level=None)
    else:
        conn = sqlite3.connect(db_file, isolation_level=None)
    conn.execute(f'PRAGMA busy_timeout = {timeout}')
    conn.execute('PRAGMA temp_store = MEMORY')
    conn.execute('PRAGMA synchronous = normal')
    conn.row_factory = sqlite3.Row
    if mode == 'r':
        conn.execute('BEGIN DEFERRED')
    elif mode == 'w':
        conn.execute('PRAGMA journal_mode = wal')
        conn.execute('BEGIN IMMEDIATE')
    try:
        import time, logging
        t0 = time.monotonic()
        yield conn
        elapsed = time.monotonic() - t0
        if elapsed > SLOW_QUERY_THRESHOLD:
            logging.warning('SLOW QUERY: %s: %.3fs', desc, elapsed)
        if conn.in_transaction:
            conn.execute('COMMIT')
    finally:
        conn.close()

# === Load config ===

_config_path = Path('req-config.py')
if _config_path.exists():
    _config_dir = _config_path.resolve().parent
    exec(_config_path.read_text(), globals())
else:
    _config_dir = None

key_file = os.environ.get('REQ_KEY_FILE', key_file)

# === Dynamic column discovery ===

def discover_columns():
    with open_db('r') as conn:
        input_info = conn.execute("PRAGMA table_info(input)").fetchall()
        results_info = conn.execute("PRAGMA table_info(results)").fetchall()

    input_cols = [r[1] for r in input_info]

    results_all_cols = [r[1] for r in results_info if r[1] != 'row_id']
    results_types = {r[1]: r[2].upper() for r in results_info}
    result_data_cols = [c for c in results_all_cols if c not in ('run_id', 'req_id')]

    return input_cols, result_data_cols, results_all_cols, results_types

input_cols, result_data_cols, results_all_cols, results_types = discover_columns()
result_col_idx = {col: i for i, col in enumerate(result_data_cols)}
results_insert_sql = f"INSERT INTO results ({', '.join(results_all_cols)}) VALUES ({', '.join('?' for _ in results_all_cols)})"

# === API setup ===

if x_title is None:
    raise RuntimeError("x_title must be set in req-config.py")

OPENROUTER_API_KEY = Path(key_file).read_text().rstrip()
url = "https://openrouter.ai/api/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "X-Title": x_title,
    "HTTP-Referer": http_referer,
}

def _resolve_file(name):
    p = Path(name)
    if p.exists():
        return p
    if _config_dir:
        p2 = _config_dir / name
        if p2.exists():
            return p2
    return p  # fall back to original for the error message

instructions = _resolve_file(system_prompt).read_text(encoding="utf-8")

# === MISC
