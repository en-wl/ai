import sqlite3
import random
from math import ceil,floor
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import re
from decimal import Decimal
from pathlib import Path
from dataclasses import dataclass, field
from unidecode import unidecode
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import defaultdict
import time
import logging
import sys
import signal
import subprocess

ENABLE_REDO = False
def input_rows(conn, model):
    return conn.execute("select * from input where uid in (select uid from candidates where model = ?)",
                       (model,))

#ENABLE_REDO = True
#def input_rows(conn, model):
#   return conn.execute("select * from input")

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

#temp_override = 0.15
temp_override = None

OPENROUTER_API_KEY = Path("key.txt").read_text().rstrip()
url = "https://openrouter.ai/api/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "X-Title": "Corpus Size Scoring",
    "HTTP-Referer": "https://github.com/en-wl/wordlist",
}

instructions = Path("system_prompt.md").read_text(encoding="utf-8")

class BatchSession:
    def __init__(self, model_alias, batch_size):
        self.input_rows = {}
        self.input_lemmas = {}

        self.header = '|'.join(['uid', 'lemmas', 'base_pos'])
        with sqlite3.connect('data.db') as conn:
            for row in input_rows(conn, model_alias):
                uid, lemmas, base_pos = row
                row = '|'.join(str(col) for col in [uid, lemmas, base_pos])
                self.input_lemmas[uid] = set(unidecode(lemma.strip().lower()) for lemma in lemmas.split(','))
                self.input_rows[uid] = row

        self.batch_size = batch_size
        self.uids_todo = list(self.input_rows.keys())
        random.shuffle(self.uids_todo)

        model_config = models_config[model_alias]
        temperature = model_config.get('temperature', 1) if temp_override is None else temp_override
        reasoning = model_config.get('reasoning', 'n/a')

        with sqlite3.connect('data.db') as conn:
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

@dataclass
class ParseResult:
    rows: list = field(default_factory=list)
    model_notes: str = None
    errors: list = field(default_factory=list)



def process_llm_response(content, expected_uids, input_lemmas):
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

            # Check for malformed row (cols < 6)
            if len(cells) < 6:
                errors.append({
                    'uid': uid,
                    'error_code': "MALFORMED_ROW",
                    'error_msg': f"Malformed row (cols < 6)",
                    'orig_line': line
                })
                continue

            lemma_str = cells[1]
            pos = cells[2]
            size_str = cells[3].lower()
            borderline_str = cells[4].lower()
            size_notes = " | ".join(cells[5:]) # Join remaining cells

            # Check lemma
            normalized_lemmas = set(unidecode(l.strip().lower()) for l in lemma_str.split(','))
            if uid is not None and normalized_lemmas.isdisjoint(input_lemmas[uid]):
                errors.append({
                    'uid': uid,
                    'error_code': "LEMMA_MISMATCH",
                    'error_msg': f"Lemma mismatch: {normalized_lemmas}",
                    'orig_line': line
                })
                continue

            # Parse and check size
            if size_str == 'excluded' or size_str == 'exclude':
                size = 99
            else:
                try:
                    size = int(size_str)
                except ValueError:
                    size = None
            if size not in (60, 70, 80, 99):
                errors.append({
                    'uid': uid,
                    'error_code': "INVALID_SIZE",
                    'error_msg': f"Invalid size str: {size_str}",
                    'orig_line': line
                })
                continue

            # Parse and check borderline
            if borderline_str == '' or borderline_str == 'no':
                borderline = ''
            elif borderline_str == '60/70':
                borderline = '60/70'
            elif borderline_str == '70/80':
                borderline = '70/80'
            elif borderline_str == 'incl/excl':
                if size == 80:
                    borderline = '80/99'
                else:
                    borderline = ''
            else:
                errors.append({
                    'uid': uid,
                    'error_code': "INVALID_BORDERLINE",
                    'error_msg': f"Invalid borderline str: {borderline_str}",
                    'orig_line': line
                })
                continue

            row_data = {
                'uid': uid,
                'lemmas': lemma_str,
                'pos': pos,
                'size': size,
                'borderline': borderline,
                'size_notes': size_notes,
                'normalized_lemmas': normalized_lemmas,
                'orig_line': line,
            }

            table_rows[uid].append(row_data)

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

    # iterate through table_rows and check for duplicates; only keep the
    # non-duplicates
    for rows in table_rows.values():
        if len(rows) == 1:
            res.rows.append(rows[0])
        else:
            for row in rows:
                res.errors.append({
                    'uid': row['uid'],
                    'error_code': "DUPLICATE_UID",
                    'error_msg': "Duplicate UID.",
                    'orig_line': row['orig_line'],
                })

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
retry_strategy = Retry(
    total=None,
    backoff_max=1.2,
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
        return (None, None, False)

    logging.info(f"starting {run.run_id}/{model_alias} #{seq_id+1}/{seq_id+run.num_batches}; rows: {len(uids)}")

    model = models_config[model_alias]
    model_id = model['name']

    rows_content = ''.join(f'{run.input_rows[uid]}\n' for uid in uids if uid in run.input_rows)
    data = f"{run.header}\n{rows_content}"
    payload = {
        "model": model_id,
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
    content = ""

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
    )
    http_session = requests.Session()
    http_session.mount("https://", adapter)

    try:
        resp = http_session.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        resp_data = resp.json()
        content = resp_data["choices"][0]["message"]["content"]
    except requests.exceptions.HTTPError as e:
        error_msg = f"{type(e).__name__}: {e}"
        if e.response is None:
            resp_data = {"error": error_msg}
        else:
            resp = e.response
            if resp.status_code == 429:
                logging.info(f"rate limited (429): {run.run_id}/{model_alias} #{seq_id+1}.")
                return (set(uids), True)
            resp_data = {"error": error_msg,
                         "status_code": resp.status_code,
                         "reason": resp.reason,
                         "body": resp.text}
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        resp_data = {"error": error_msg}

    parsed_result, failed, redo = process_llm_response(content, uids, run.input_lemmas)

    if not parsed_result.rows and error_msg is None:
        error_code = parsed_result.errors[-1]['error_code'] if parsed_result.errors else "UNKNOWN"
        error_msg = f"No Results: {error_code}"

    while True:
        try:
            with sqlite3.connect('data.db') as conn:
                cur = conn.execute(
                    """INSERT INTO requests (entry_time, run_id, batch_size, error, model_notes)
                       VALUES ((julianday('now') - 2440587.5) * 86400.0, ?, ?, ?, ?)""",
                    (run.run_id, len(uids), error_msg, parsed_result.model_notes))
                req_id = cur.lastrowid

                conn.execute(
                    "INSERT INTO raw_data (req_id, request, response) VALUES (?, ?, ?)",
                    (req_id, json.dumps(payload), json.dumps(resp_data))
                )

                conn.executemany(
                    """INSERT INTO results
                        (uid, run_id, req_id, lemmas, pos, size, borderline, size_notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    ((row['uid'], run.run_id, req_id, row['lemmas'], row['pos'], row['size'],
                      row['borderline'], row['size_notes'])
                     for row in parsed_result.rows))

                conn.executemany(
                    """INSERT INTO errors (req_id, uid, error_code, error_msg, orig_line)
                        VALUES (?, ?, ?, ?, ?)""",
                    ((req_id, err['uid'], err['error_code'], err['error_msg'], err['orig_line'])
                     for err in parsed_result.errors)
                )

                conn.commit()
                break  # Success, exit the retry loop
        except sqlite3.OperationalError as e:
            logging.info(f"SQLite timeout for {model_alias} #{seq_id+1}: {e}. Retrying in 1 second...")
            time.sleep(1)
            continue

    prefix = f"FAILED: {error_msg}" if error_msg else "FINISHED"
    logging.info(f"{prefix}: {run.run_id}/{model_alias} #{seq_id+1}; id: {req_id}; redos: {len(redo)}.")
    return (failed, redo, False)

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
model_alias = None
def main(max_workers, batch_size):
    run = BatchSession(model_alias, batch_size)

    in_flight = set()
    seq_id = 0
    effective_max_workers = max_workers

    shutdown_str = ""
    def enter_shutdown_mode(reason):
        nonlocal shutdown_str
        if shutdown_str:
            return
        logging.warning(f"*** ENTERING SHUTDOWN MODE: {reason} ***")
        shutdown_str = f"{reason}: "
        # cause the loop to exit cleanly after draining in-flight
        run.uids_todo.clear()

    def handle_result(future):
        nonlocal effective_max_workers
        try:
            failed, redo, hit_429 = future.result()
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

        for uid in failed:
            failed_uids[uid] = failed_uids.get(uid, 0) + 1
        
        if ENABLE_REDO:
            for uid in redo:
                if failed_uids.get(uid, 0) >= 3:
                    logging.info(f"skipping {uid}: to many failures")
                    continue
                run.uids_todo.append(uid)


    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Main loop: continue while requests are in flight OR there's work to do
        while in_flight or run.uids_todo:
            loop_start = time.time()

            # At capacity: block until at least one request completes
            if len(in_flight) >= effective_max_workers:
                done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                for f in done:
                    assert(f.done())
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
            elif in_flight:
                # Have work but waiting for batch to fill up; log that we're waiting
                logging.info(f"{shutdown_str}{len(in_flight)} requests still pending")

            # Poll for completed requests without blocking
            for f in [f for f in in_flight if f.done()]:
                in_flight.remove(f)
                handle_result(f)

            # Ensure at least 2 seconds between loop iterations
            elapsed = time.time() - loop_start
            if elapsed < 2:
                time.sleep(2 - elapsed)

        if shutdown_str:
            sys.exit(1)

    return set(run.input_rows.keys())

if __name__ == '__main__':
    # Set up signal handler for Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)

    model_alias = sys.argv[1]
    batch_size = models_config[model_alias]['batch_size']
    max_workers = 100
    if len(sys.argv) > 2 and sys.argv[2] != '-':
        max_workers = int(sys.argv[2])
    if len(sys.argv) > 3:
        batch_size = int(sys.argv[3])

    with sqlite3.connect('data.db') as conn:
        conn.executemany("insert or ignore into models values (?)",
                         ((k,) for k in models_config.keys()))
        

    print(f"model: {model_alias}; max_workers: {max_workers}; batch_size: {batch_size}")
    time.sleep(2)

    while True:
       subprocess.run(['python3', 'populate_size_scores.py'], check=True)
       uids = main(max_workers, batch_size)
       if not uids or uids <= failed_uids.keys():
          break
       prev_uid = uids
   
