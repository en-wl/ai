import sqlite3
import random
from math import ceil,floor
import os
import requests
from requests.adapters import HTTPAdapter
import urllib3
from urllib3.util.retry import Retry
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import NamedTuple
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import defaultdict
import time
import logging
import sys
import signal
import subprocess
class RetryNoTimeout(Retry):
    """Retry on status/connection errors but not on timeouts."""
    def increment(self, method=None, url=None, response=None, error=None, **kwargs):
        if isinstance(error, urllib3.exceptions.TimeoutError):
            raise error
        return super().increment(method=method, url=url, response=response,
                                 error=error, **kwargs)

# === Configurable defaults (can be overridden by req-config.py) ===

db = 'data.db'
system_prompt = 'system_prompt.md'
post_run = None
ENABLE_REDO = False
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

class BatchSession:
    def __init__(self, model_alias, batch_size):
        self.input_strings = {}
        self.input_data = {}

        self.header = '|'.join(input_cols)
        with sqlite3.connect(db) as conn:
            for row in input_rows(conn, model_alias):
                uid = row[0]
                values = [str(col) for col in row]
                self.input_strings[uid] = '|'.join(values)
                self.input_data[uid] = dict(zip(input_cols, row))

        self.batch_size = batch_size
        self.uids_todo = list(self.input_strings.keys())
        random.shuffle(self.uids_todo)

        model_config = models_config[model_alias]
        temperature = model_config.get('temperature', 1) if temp_override is None else temp_override
        reasoning = model_config.get('reasoning', 'n/a')

        with sqlite3.connect(db) as conn:
            cur = conn.execute(
                """INSERT INTO runs (model, start_time, batch_size, temperature, reasoning_effort, sample_type)
                   VALUES (?, (julianday('now') - 2440587.5) * 86400.0, ?, ?, ?, 'random')""",
                (model_alias, self.batch_size, temperature, reasoning)
            )
            self.run_id = cur.lastrowid
            conn.commit()

    def next(self):
        self.num_batches = ceil(len(self.uids_todo) / self.batch_size)
        size = floor(len(self.uids_todo) / self.num_batches) if self.num_batches > 0 else 0
        uids = self.uids_todo[-size:]
        del self.uids_todo[-size:]
        return uids

class RequestResult(NamedTuple):
    failed: set = frozenset()
    redo: set = frozenset()
    completed: set = frozenset()
    hit_429: bool = False
    error_class: str = None  # 'connection', 'model', or None

@dataclass
class ParseResult:
    rows: list = field(default_factory=list)
    model_notes: str = None
    errors: list = field(default_factory=list)


def process_llm_response(content, expected_uids, input_data):
    lines = content.splitlines()
    table_rows = defaultdict(list)
    model_notes = []
    errors = []

    # State flags
    in_table = False
    headers_found = False

    # Regex to define a table row (starts and ends with |)
    row_pattern = re.compile(r'^\s*\|.*\|\s*$')

    for line in lines:

        # Check if the line looks like a table row
        if row_pattern.match(line):

            # 1. Check for Separator Line (e.g., |---|---|)
            # If found, we are definitely in a table.
            if set(line) <= {'|', '-', ' ', ':'}:
                in_table = True
                headers_found = True
                continue # Skip the separator line itself

            # 2. Start Detection (if we aren't in a table yet)
            if not in_table:
                # We found a pipe-delimited line but haven't seen a separator yet.
                # Determine if this is a Header or Data based on the first cell.
                cells = [c.strip() for c in line.split('|')[1:-1]]

                if cells:
                    first_cell = cells[0]
                    # If the first cell is a number, it's a Data Row (Header missing/skipped)
                    if first_cell.isdigit():
                        in_table = True
                        headers_found = True
                        # Do NOT continue; fall through to process this line as data
                    else:
                        # If not a number, assume it's a Header Row
                        in_table = True
                        headers_found = True
                        continue # Skip the header line

            # 3. Process Data Row
            # We parse the row if we are in_table (and it wasn't a separator or header)
            cells = [c.strip() for c in line.split('|')[1:-1]]

            # Attempt to extract UID first
            uid = None
            if len(cells) > 0:
                uid_str = cells[0]
                try:
                    uid = int(uid_str)
                except ValueError:
                    errors.append({
                        'uid': None,
                        'error_code': "INVALID_UID",
                        'error_msg': f"Invalid UID str: {uid_str}",
                        'orig_line': line
                    })
                    continue
                if uid not in expected_uids:
                    errors.append({
                        'uid': None,
                        'error_code': "UID_UNKNOWN",
                        'error_msg': f"UID {uid} returned but not requested.",
                        'orig_line': line,
                    })
                    continue

            # Check for malformed row
            if len(cells) < len(result_data_cols):
                errors.append({
                    'uid': uid,
                    'error_code': "MALFORMED_ROW",
                    'error_msg': f"Malformed row (cols < {len(result_data_cols)})",
                    'orig_line': line
                })
                continue

            # Join overflow cells into last column
            if len(cells) > len(result_data_cols):
                cells[len(result_data_cols)-1] = " | ".join(cells[len(result_data_cols)-1:])
                cells = cells[:len(result_data_cols)]

            # Map cells to column names
            row = dict(zip(result_data_cols, cells))
            row['uid'] = uid  # ensure uid is int

            # validate_row callback
            if validate_row is not None:
                row, err = validate_row(row, input_data[uid])
                if err is not None:
                    errors.append({
                        'uid': uid,
                        'error_code': err['error_code'],
                        'error_msg': err['error_msg'],
                        'orig_line': line
                    })
                    continue

            # Post-validation type fixes
            try:
                for col in result_data_cols:
                    if col == 'uid':
                        continue
                    col_type = results_types.get(col, '')
                    val = row[col]
                    if col_type == 'INTEGER':
                        row[col] = int(val)
                    elif col_type == 'REAL':
                        row[col] = float(val)
            except (TypeError, ValueError):
                errors.append({
                    'uid': uid,
                    'error_code': "INVALID_TYPE",
                    'error_msg': f"Column '{col}' expected {col_type} but got: {val}",
                    'orig_line': line
                })
                continue

            row['orig_line'] = line
            table_rows[uid].append(row)

        else:
            # Line does not match |...| pattern
            if in_table:
                # If we were in a table and hit a non-table line, the table is over.
                in_table = False
                model_notes.append(line)
            elif headers_found:
                # Notes after the table
                model_notes.append(line)

    if not headers_found:
        errors.append({
            'uid': None,
            'error_code': "NO_TABLE",
            'error_msg': "No table structure detected in response.",
            'orig_line': None,
        })

    res = ParseResult(
        rows=[],
        model_notes="\n".join(model_notes).strip(),
        errors=errors,
    )

    for rows in table_rows.values():
        res.rows.extend(rows)

    completed = set(row['uid'] for row in res.rows)
    if len(completed) == 0:
        if not res.errors:
            res.errors.append({
                'uid': None,
                'error_code': "NO_DATA",
                'error_msg': "No data.",
                'orig_line': None,
            })
        redo = set(expected_uids)
        failed = set()
    elif len(completed) / len(expected_uids) < 0.65:
        res.rows = []
        res.errors.append({
            'uid': None,
            'error_code': "BAD_ROWS",
            'error_msg': f"Too many bad rows ({len(completed)}/{len(expected_uids)}).",
            'orig_line': None,
        })
        redo = set(expected_uids)
        failed = set(expected_uids) - completed
    else:
        redo = set(expected_uids) - completed
        failed = set(expected_uids) - completed

    return res, failed, redo


# Rate limit: 429
# Standard server errors: 500, 502, 503, 504
# Cloudflare errors: 520, 521, 522, 524
status_codes_to_retry = [429, 500, 502, 503, 504, 520, 521, 522, 524]
retry_strategy = RetryNoTimeout(
    total=3,
    backoff_factor=0.25,
    status_forcelist=status_codes_to_retry,
    allowed_methods=["POST"],
    raise_on_status=False,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def model_specific_instructions(model):
    special = model.get('special', None)
    if special is None:
        return instructions
    return f"""{instructions}

## Special Instructions

{model['special']}
"""

def send_request(run, model_alias, seq_id, uids):
    if not uids:
        return RequestResult()

    logging.info(f"starting {run.run_id}/{model_alias} #{seq_id+1}/{seq_id+run.num_batches}; UIDs: {len(uids)}")

    model = models_config[model_alias]
    model_id = model['name']

    rows_content = ''.join(f'{run.input_strings[uid]}\n' for uid in uids if uid in run.input_strings)
    data = f"{run.header}\n{rows_content}"
    payload = {
        "model": model_id,
        "stream": True,
        "provider": {
            "only": model['providers']
        },
        "messages": [
            {"role": "system", "content": model_specific_instructions(model)},
            {"role": "user", "content": data},
        ],
    }

    if temp_override is not None:
       payload['temperature'] = temp_override
    elif 'temperature' in model:
       payload['temperature'] = model['temperature']
       if 'top_p' in model:
           payload['top_p'] = model['top_p']

    reasoning = model.get('reasoning', None)
    if reasoning is not None:
        payload["reasoning"] = {
            "effort": reasoning,
            "summary": "concise",
            #"max_tokens": 4000,
        }

    max_output = model.get('max_output', None)
    if max_output is not None:
        payload['max_output'] = max_output

    stop_text = model.get("stop", None)
    if stop_text is not None:
        payload['stop'] = stop_text

    parsed_result = ParseResult()
    error_msg = None
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
    )
    http_session = requests.Session()
    http_session.mount("https://", adapter)

    cfg = models_config[model_alias]
    timeout = cfg.get('timeout', 30)

    data = {}
    send_time = time.time()
    try:
        resp = http_session.post(url, headers=headers, json=payload, timeout=timeout, stream=True)
        resp.raise_for_status()
        last_data_time = time.time()
        for raw in resp.iter_lines():
            line = raw.decode('utf-8')
            now = time.time()
            if not line.startswith('data: '):
                if now - last_data_time > timeout:
                    raise requests.exceptions.Timeout(f"No data received for {timeout}s")
                continue
            data_str = line[6:]
            if data_str == '[DONE]':
                break

            chunk = json.loads(data_str)
            if not data:
                last_data_time = now
                data = chunk.copy()
                data['object'] = 'reconstructed'
                message = {
                    'content': ''
                }
                data['choices'] = [{
                    'message': message
                }]

            if chunk['choices']:
                choice_data = chunk['choices'][0]
            else:
                choice_data = {}

            for key, value in choice_data.get('delta', {}).items():
                if key in ('content', 'reasoning') and value:
                    last_data_time = now
                    message[key] = message.get(key, '') + value
                elif key in ('reasoning_details'):
                    # fixme: merge
                    pass

            if choice_data.get('finish_reason', None) is not None:
                data['choices'][0]['finish_reason'] = choice_data['finish_reason']
                data['choices'][0]['native_finish_reason'] = choice_data.get('native_finish_reason', None)

            error = chunk.get('error', None)
            if error:
                error_msg = error.get('message', str(error))
                data['error'] = error

            usage = chunk.get('usage', None)
            if usage is not None:
                last_data_time = now
                data['usage'] = usage

            if now - last_data_time > timeout:
                raise requests.exceptions.Timeout(f"No data received for {timeout}s")


    except requests.HTTPError as e:
        error_msg = f"{type(e).__name__}: {e}"
        if e.response is None:
            data = {"error": error_msg}
        else:
            resp = e.response
            if resp.status_code == 429:
                logging.info(f"rate limited (429): {run.run_id}/{model_alias} #{seq_id+1}.")
                return RequestResult(redo=set(uids), hit_429=True)
            data = {"error": error_msg,
                    "status_code": resp.status_code,
                    "reason": resp.reason,
                    "body": resp.text}
    except (requests.exceptions.Timeout, urllib3.exceptions.TimeoutError) as e:
        error_msg = str(e)
        data['error'] = error_msg
    except Exception as e:
        logging.exception(e)
        error_msg = f"{type(e).__name__}: {e}"
        data["error"] = error_msg

    if error_msg:
        content = ''
    else:
        content = data["choices"][0]["message"]["content"]

    parsed_result, failed, redo = process_llm_response(content, uids, run.input_data)

    if not parsed_result.rows and error_msg is None:
        error_code = parsed_result.errors[-1]['error_code'] if parsed_result.errors else "UNKNOWN"
        error_msg = f"No Results: {error_code}"

    while True:
        try:
            with sqlite3.connect(db) as conn:
                cur = conn.execute(
                    """INSERT INTO requests (entry_time, send_time, run_id, batch_size, error, model_notes)
                       VALUES ((julianday('now') - 2440587.5) * 86400.0, ?, ?, ?, ?, ?)""",
                    (send_time, run.run_id, len(uids), error_msg, parsed_result.model_notes))
                req_id = cur.lastrowid

                conn.execute(
                    "INSERT INTO raw_data (req_id, request, response) VALUES (?, ?, ?)",
                    (req_id, json.dumps(payload), json.dumps(data))
                )

                # Insert results row-by-row to catch constraint violations
                insert_errors = []
                for row in parsed_result.rows:
                    values = tuple(
                        row.get(c, run.run_id if c == 'run_id' else req_id if c == 'req_id' else '')
                        for c in results_all_cols
                    )
                    try:
                        conn.execute(results_insert_sql, values)
                    except sqlite3.IntegrityError as e:
                        insert_errors.append({
                            'uid': row['uid'],
                            'error_code': 'CONSTRAINT_VIOLATION',
                            'error_msg': str(e),
                            'orig_line': row.get('orig_line'),
                        })
                constraint_failed = set(e['uid'] for e in insert_errors)
                conn.executemany("delete from results where req_id = ? and uid = ?",
                                 ((req_id, uid) for uid in constraint_failed))

                conn.executemany(
                    """INSERT INTO errors (req_id, uid, error_code, error_msg, orig_line)
                        VALUES (?, ?, ?, ?, ?)""",
                    ((req_id, err['uid'], err['error_code'], err['error_msg'], err['orig_line'])
                     for err in parsed_result.errors)
                )

                conn.commit()
                break  # Success, exit the retry loop
        except sqlite3.OperationalError as e:
            if "locked" not in str(e):
                raise
            logging.info(f"SQLite locked for {model_alias} #{seq_id+1}: {e}. Retrying in 1 second...")
            time.sleep(1)
            continue

    # Classify error
    if error_msg:
        error_class = 'connection'
    elif not parsed_result.rows:
        error_class = 'model'
    else:
        error_class = None

    # Constraint violations always count as per-UID failures
    failed |= constraint_failed
    redo |= constraint_failed

    completed = set(row['uid'] for row in parsed_result.rows) - constraint_failed

    if error_msg and len(error_msg) > 50:
        error_msg = error_msg[0:49] + "…"

    prefix = f"FAILED: {error_msg}" if error_msg else "FINISHED"
    ok_cnt = len(completed)
    failed_cnt = len(failed)
    redo_cnt = len(redo - failed)
    logging.info(f"{prefix}: {run.run_id}/{model_alias} #{seq_id+1}; id: {req_id}; ok/redo/failed: {ok_cnt}/{redo_cnt}/{failed_cnt}")
    return RequestResult(failed=failed, redo=redo, completed=completed, error_class=error_class)

shutdown_requested = False
interrupt_count = 0

# Rate limit tracking
rate_limit_hits = []
RATE_LIMIT_WINDOW = 30  # seconds
RATE_LIMIT_THRESHOLD = 3  # hits within window to trigger cap

def record_rate_limit():
    """Record a 429 hit and return True if threshold exceeded."""
    now = time.time()
    rate_limit_hits.append(now)
    # Prune old entries outside the window
    rate_limit_hits[:] = [t for t in rate_limit_hits if now - t < RATE_LIMIT_WINDOW]
    return len(rate_limit_hits) >= RATE_LIMIT_THRESHOLD

def signal_handler(sig, frame):
    global shutdown_requested, interrupt_count
    interrupt_count += 1

    if interrupt_count == 1:
        logging.info("\nCtrl-C detected. Finishing current requests and shutting down gracefully...")
        logging.info("Press Ctrl-C again to force immediate exit.")
        shutdown_requested = True
    else:
        logging.info("\nForce exit requested. Exiting immediately.")
        os._exit(128+sig)

failed_uids = {}
consecutive_errors = 0
model_alias = None
def main(max_workers, batch_size):
    run = BatchSession(model_alias, batch_size)

    in_flight = set()
    seq_id = 0
    effective_max_workers = max_workers

    LAST_LOG_INTERVAL = 20
    last_log_time = None

    shutdown_str = ""
    def enter_shutdown_mode(reason, prefix = None):
        nonlocal shutdown_str, last_log_time
        if shutdown_str:
            return
        if prefix is None:
            prefix = reason
        logging.warning(f"*** ENTERING SHUTDOWN MODE: {reason} ***")
        shutdown_str = f"{prefix}: "
        # cause the loop to exit cleanly after draining in-flight
        run.uids_todo.clear()
        last_log_time = None

    def handle_result(future):
        global consecutive_errors
        nonlocal effective_max_workers, last_log_time
        try:
            failed, redo, completed, hit_429, error_class = future.result()
        except Exception as e:
            logging.exception(f"ERROR: {e}")
            enter_shutdown_mode("failure mode")
            return

        if shutdown_str:
            return

        if hit_429 and record_rate_limit():
            old = effective_max_workers
            effective_max_workers = max(1, min(len(in_flight), old-1))
            logging.warning(f"*** RATE LIMITED: max_workers capped {old} -> {effective_max_workers} ***")
            run.uids_todo += redo
            return

        # Consecutive systematic/connection error tracking
        if error_class is None:
            consecutive_errors = 0
        else:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                enter_shutdown_mode("5 consecutive failures", "failure mode")
                return

        for uid in failed:
            failed_uids[uid] = failed_uids.get(uid, 0) + 1

        if ENABLE_REDO:
            for uid in redo:
                if failed_uids.get(uid, 0) >= 3:
                    logging.info(f"skipping {uid}: to many failures")
                    continue
                run.uids_todo.append(uid)

        last_log_time = None


    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Main loop: continue while requests are in flight OR there's work to do
        while in_flight or run.uids_todo:
            loop_start = time.time()

            if len(in_flight) >= effective_max_workers:
                logging.info(f"{shutdown_str}{len(in_flight)} requests in flight: waiting for at least one to finish")
                # At capacity: block until at least one request completes
                done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                for f in done:
                    handle_result(f)
            else:
                # Poll for completed requests without blocking
                for f in [f for f in in_flight if f.done()]:
                    in_flight.remove(f)
                    handle_result(f)

            # Graceful shutdown: drain in-flight requests without submitting new ones
            if shutdown_requested:
                enter_shutdown_mode("shutdown requested")

            # Submit new work if:
            #   - there's work to do, AND
            #   - redo is disabled (submit any size batch), OR
            #   - we have a full batch worth of work, OR
            #   - nothing in flight (submit final partial batch)
            if run.uids_todo and (not ENABLE_REDO or len(run.uids_todo) >= batch_size or not in_flight):
                uids = run.next()
                f = executor.submit(send_request, run, model_alias, seq_id, list(uids))
                seq_id += 1
                in_flight.add(f)
                last_log_time = time.time()
            elif in_flight and (last_log_time is None or time.time() - last_log_time >= LAST_LOG_INTERVAL):
                logging.info(f"{shutdown_str}{len(in_flight)} requests still pending")
                last_log_time = time.time()

            # Ensure at least 2 seconds between loop iterations
            elapsed = time.time() - loop_start
            if elapsed < 2:
                time.sleep(2 - elapsed)

        if shutdown_str:
            sys.exit(1)

    return set(run.input_strings.keys())

if __name__ == '__main__':
    # Set up signal handler for Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)

    if len(sys.argv) < 2:
        print(f"usage: python3 -m req <model> [max_workers] [batch_size]")
        print(f"\navailable models: {', '.join(models_config.keys())}")
        sys.exit(1)

    model_alias = sys.argv[1]
    batch_size = models_config[model_alias]['batch_size']
    max_workers = 100
    if len(sys.argv) > 2 and sys.argv[2] != '-':
        max_workers = int(sys.argv[2])
    if len(sys.argv) > 3:
        batch_size = int(sys.argv[3])

    with sqlite3.connect(db) as conn:
        conn.executemany("insert or ignore into models values (?)",
                         ((k,) for k in models_config.keys()))


    print(f"model: {model_alias}; max_workers: {max_workers}; batch_size: {batch_size}")
    time.sleep(2)

    while True:
       if post_run is not None:
           subprocess.run(post_run, check=True)
       uids = main(max_workers, batch_size)
       if not uids or uids <= failed_uids.keys():
          break
       prev_uid = uids
