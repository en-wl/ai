#!/usr/bin/env python3
"""Re-run parsing/validation on stored raw_data responses.

Run from a project directory (e.g. size-score/):
    python3 ../misc/reparse.py
"""

import sys
import json
import sqlite3

sys.path.insert(0, '..')

from req._request import process_llm_response, store_parse_result
from req._config import db

def parse_user_message(content):
    """Parse the pipe-delimited table from the user message to reconstruct
    expected_uids and input_data."""
    lines = content.strip().splitlines()
    if not lines:
        return set(), {}

    # First line is the header: uid|word|pos|...
    header_parts = [h.strip() for h in lines[0].split('|')]

    expected_uids = set()
    input_data = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split('|')]
        try:
            uid = int(parts[0])
        except (ValueError, IndexError):
            continue
        expected_uids.add(uid)
        row = {}
        for i, col in enumerate(header_parts[1:], 1):
            row[col] = parts[i] if i < len(parts) else ''
        input_data[uid] = row

    return expected_uids, input_data


def main():
    conn = sqlite3.connect(db)

    # Get counts before
    old_results = conn.execute("SELECT count(*) FROM results").fetchone()[0]
    old_errors = conn.execute("SELECT count(*) FROM errors").fetchone()[0]

    # Clear results and errors
    conn.execute("DELETE FROM results")
    conn.execute("DELETE FROM errors")

    # Fetch all raw_data joined with requests to get run_id
    rows = conn.execute("""
        SELECT rd.req_id, r.run_id, rd.request, rd.response
        FROM raw_data rd
        JOIN requests r ON rd.req_id = r.req_id
    """).fetchall()

    total_results = 0
    total_errors = 0
    for req_id, run_id, request_json, response_json in rows:
        try:
            request = json.loads(request_json)
            response = json.loads(response_json)
        except (json.JSONDecodeError, TypeError):
            print(f"  req_id {req_id}: skipping (invalid JSON)")
            continue

        # Extract user message content (second message)
        try:
            user_content = request['messages'][1]['content']
        except (KeyError, IndexError, TypeError):
            print(f"  req_id {req_id}: skipping (no user message)")
            continue

        # Extract response content
        try:
            content = response['choices'][0]['message']['content'] or ''
        except (KeyError, IndexError, TypeError):
            content = ''

        expected_uids, input_data = parse_user_message(user_content)
        if not expected_uids:
            print(f"  req_id {req_id}: skipping (no UIDs in user message)")
            continue

        parsed_result, failed, redo = process_llm_response(content, expected_uids, input_data)

        # Determine error message (mirrors send_request logic)
        error_msg = None
        if 'error' in response and response['error']:
            err = response['error']
            error_msg = err.get('message', str(err)) if isinstance(err, dict) else str(err)
        if not parsed_result.rows and error_msg is None:
            error_code = parsed_result.errors[-1]['error_code'] if parsed_result.errors else "UNKNOWN"
            error_msg = f"No Results: {error_code}"

        constraint_failed = store_parse_result(conn, req_id, run_id, parsed_result)

        # Update requests table with new model_notes and error
        conn.execute(
            "UPDATE requests SET model_notes = ?, error = ? WHERE req_id = ?",
            (parsed_result.model_notes, error_msg, req_id)
        )

    new_results = conn.execute("SELECT count(*) FROM results").fetchone()[0]
    new_errors = conn.execute("SELECT count(*) FROM errors").fetchone()[0]

    conn.commit()
    conn.close()

    print(f"Processed {len(rows)} requests")
    print(f"Results: {old_results} -> {new_results}")
    print(f"Errors:  {old_errors} -> {new_errors}")


if __name__ == '__main__':
    main()
