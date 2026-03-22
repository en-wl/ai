import sqlite3
import json
import re
import time
import logging
from typing import NamedTuple
from dataclasses import dataclass, field
from collections import defaultdict
import requests
from requests.adapters import HTTPAdapter
import urllib3
from urllib3.util.retry import Retry

from req._config import *

# Thread safety: send_request() runs in a ThreadPoolExecutor from __main__.py,
# so all code in this module must be safe for concurrent execution.  This works
# because every function uses only local variables and read-only module-level
# config imported from _config.  The one shared mutable resource (the SQLite
# database) is accessed through short-lived per-call connections, which SQLite
# serializes internally.

class RetryNoTimeout(Retry):
    """Retry on status/connection errors but not on timeouts."""
    def increment(self, method=None, url=None, response=None, error=None, **kwargs):
        if isinstance(error, urllib3.exceptions.TimeoutError):
            raise error
        return super().increment(method=method, url=url, response=response,
                                 error=error, **kwargs)

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

    failed = set(e['uid'] for e in errors if e['uid'] is not None)
    completed = set()
    for uid, rows in table_rows.items():
        if uid in failed:
            continue
        res.rows.extend(rows)
        completed.add(uid)

    good_rows = sum(len(rows) for rows in table_rows.values())
    bad_rows = sum(1 for e in errors if e['orig_line'] is not None)

    if good_rows == 0:
        if not res.errors:
            res.errors.append({
                'uid': None,
                'error_code': "NO_DATA",
                'error_msg': "No data.",
                'orig_line': None,
            })
        redo = set(expected_uids)
    elif good_rows < 2 * bad_rows:
        res.rows = []
        res.errors.append({
            'uid': None,
            'error_code': "BAD_ROWS",
            'error_msg': f"Too many bad rows ({bad_rows} bad vs {good_rows} good).",
            'orig_line': None,
        })
        redo = set(expected_uids)
    else:
        redo = set(expected_uids) - completed
        missing = redo - failed
        if missing:
            res.errors.append({
                'uid': None,
                'error_code': "MISSING_UIDS",
                'error_msg': f"Missing {len(missing)}/{len(expected_uids)} UIDs.",
                'orig_line': None,
            })

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

            if abort_event.is_set():
                logging.info(f"aborting: {run.run_id}/{model_alias} #{seq_id+1}")
                break

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

    try:
        content = data["choices"][0]["message"]["content"] or '' # to guard against None value
    except (KeyError, IndexError, TypeError):
        content = ''

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
