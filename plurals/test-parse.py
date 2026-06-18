#!/usr/bin/env python3
"""Offline test of the plurals parse + validate pipeline (no network).

Feeds a hand-written model response through the real framework parser
(UidsRequest.process_response) and checks the resulting rows/errors.  This
exercises schema discovery (_expected==4), validate_row, type coercion, and the
Markdown-table parser -- everything except the live API.

The test cases are built from whatever rows are actually in the `input` table,
so the test adapts automatically to dedup (init.sh) and to changes in
input.tsv; it never references a uid that might have been deduped away.

Run from this directory (env vars default below, so plain `python3
test-parse.py` works too):

    REQ_KEY_FILE=/dev/null REQ_DEEPINFRA_KEY_FILE=/dev/null REQ_MODE=ONCE \\
        python3 test-parse.py

Requires data.db to exist (run ./init.sh first).
"""

import os
import sys
from pathlib import Path

# Must be set before importing req._config (it reads the key files and REQ_MODE
# at import time).  /dev/null keeps the test off the real keys dir.
os.environ.setdefault('REQ_MODE', 'ONCE')
os.environ.setdefault('REQ_KEY_FILE', '/dev/null')
os.environ.setdefault('REQ_DEEPINFRA_KEY_FILE', '/dev/null')

_here = Path(__file__).resolve().parent
os.chdir(_here)                        # _config uses relative 'req-config.py'/'data.db'
sys.path.insert(0, str(_here.parent))  # so `import req...` resolves

from req._uids_request import UidsBatchSession, UidsRequest
from req._request import PromptResult


def main():
    session = UidsBatchSession('gpt-oss-120b', batch_size=100, run_id=None)

    # Pick 7 distinct real input rows and assign each a test role.  Driven by
    # the live `input` table so it adapts to whatever survives dedup.
    picks = sorted(session.input_data)[:7]
    assert len(picks) == 7, f"need at least 7 input rows, have {len(session.input_data)}"
    u_clean, u_rare, u_invalid, u_mismatch, u_badcat, u_pad, u_dup = picks

    def pl(uid):
        return session.input_data[uid]['plural']

    # Cases the plan calls out:
    #   clean natural / ", rare form" / invalid+notes / padded 3-col row /
    #   deduped identical row  -> good rows (plural echoed verbatim)
    #   wrong plural -> PLURAL_MISMATCH ; bogus category -> INVALID_CATEGORY
    lines = [
        "|uid|plural|category|notes|",
        "|---|---|---|---|",
        f"|{u_clean}|{pl(u_clean)}|natural|-|",
        f"|{u_rare}|{pl(u_rare)}|natural, rare form|-|",
        f"|{u_invalid}|{pl(u_invalid)}|invalid|some reason here|",
        f"|{u_mismatch}|{pl(u_mismatch)}x|natural|-|",   # plural doesn't match input
        f"|{u_badcat}|{pl(u_badcat)}|frobnicated|-|",    # not a valid category
        f"|{u_pad}|{pl(u_pad)}|natural|",                # 3 columns, notes omitted
        f"|{u_dup}|{pl(u_dup)}|natural|-|",
        f"|{u_dup}|{pl(u_dup)}|natural|-|",              # identical duplicate
    ]
    response = "\n".join(lines) + "\n"

    expected_rows = {
        u_clean:   {'plural': pl(u_clean),   'category': 'natural',            'notes': '-'},
        u_rare:    {'plural': pl(u_rare),    'category': 'natural, rare form', 'notes': '-'},
        u_invalid: {'plural': pl(u_invalid), 'category': 'invalid',            'notes': 'some reason here'},
        u_pad:     {'plural': pl(u_pad),     'category': 'natural',            'notes': ''},
        u_dup:     {'plural': pl(u_dup),     'category': 'natural',            'notes': '-'},
    }
    expected_errors = {u_mismatch: 'PLURAL_MISMATCH', u_badcat: 'INVALID_CATEGORY'}

    req = UidsRequest(session, seq_id=0, data=picks)
    processed, _notes = req.process_response(
        PromptResult(payload={}, send_time=0, content=response))

    failures = []

    # --- rows ---
    rows_by_uid = {}
    for r in processed.rows:
        uid = r['uid']
        if uid in rows_by_uid:
            failures.append(f"uid {uid} returned more than once (dedupe failed)")
        rows_by_uid[uid] = r

    if set(rows_by_uid) != set(expected_rows):
        failures.append(f"row uids {sorted(rows_by_uid)} != expected {sorted(expected_rows)}")

    for uid, exp in expected_rows.items():
        got = rows_by_uid.get(uid)
        if got is None:
            continue
        for col, val in exp.items():
            if got.get(col) != val:
                failures.append(f"uid {uid} {col}={got.get(col)!r} != expected {val!r}")

    # --- errors ---
    err_by_uid = {e['uid']: e['error_code'] for e in processed.errors if e['uid'] is not None}
    general_errors = [e['error_code'] for e in processed.errors if e['uid'] is None]
    if general_errors:
        failures.append(f"unexpected general errors: {general_errors}")
    if err_by_uid != expected_errors:
        failures.append(f"errors {err_by_uid} != expected {expected_errors}")

    # --- failed set ---
    if processed.failed != set(expected_errors):
        failures.append(f"failed {processed.failed} != expected {set(expected_errors)}")

    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        print("\nrows:", processed.rows)
        print("errors:", processed.errors)
        sys.exit(1)

    print(f"PASS: {len(processed.rows)} rows, {len(processed.errors)} errors as expected")


if __name__ == '__main__':
    main()
