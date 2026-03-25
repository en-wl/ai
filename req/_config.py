import sqlite3
import threading
from pathlib import Path

# === Configurable defaults (can be overridden by req-config.py) ===

db = 'data.db'
system_prompt = 'system_prompt.md'
post_run = None
ENABLE_REDO = False
abort_event = threading.Event()
temp_override = None
validate_row = None
key_file = 'key.txt'
x_title = None  # required — config must set this
http_referer = 'https://github.com/en-wl/wordlist'

def input_rows(conn, model):
    return conn.execute("select * from input where uid in (select uid from candidates where model = ?)",
                       (model,))

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
        "providers": ["deepinfra/turbo"], # deepinfra/bf16  ["crusoe/bf16"],
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
        "providers": ["deepinfra/base"],
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
    "qwen3-235b-a22b-thinking": {
        "name": "qwen/qwen3-235b-a22b-thinking-2507",
        "providers": ["deepinfra/fp8", "novita/fp8", "atlas-cloud/fp8"],
        "reasoning": "minimal",
        "batch_size": 35,
        "max_output": 32000,
    }
}

# === Load config ===

_config_path = Path('req-config.py')
if _config_path.exists():
    exec(_config_path.read_text(), globals())

# === Dynamic column discovery ===

def discover_columns(db_path):
    with sqlite3.connect(db_path) as conn:
        input_info = conn.execute("PRAGMA table_info(input)").fetchall()
        results_info = conn.execute("PRAGMA table_info(results)").fetchall()

    input_cols = [r[1] for r in input_info]

    results_all_cols = [r[1] for r in results_info]
    results_types = {r[1]: r[2].upper() for r in results_info}
    result_data_cols = [c for c in results_all_cols if c not in ('run_id', 'req_id')]

    return input_cols, result_data_cols, results_all_cols, results_types

input_cols, result_data_cols, results_all_cols, results_types = discover_columns(db)
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

instructions = Path(system_prompt).read_text(encoding="utf-8")
