#!/usr/bin/env python3
"""Rebuild the `results` table from `raw_data` by re-running the parsing /
storage code in variant.py.  Useful after fixing VariantRequest's parser.

Usage:
    ./reprocess.py [run_id ...]

With no arguments every raw_data row is reprocessed (full rebuild of results).
Given one or more run_ids, only those runs are touched (their existing results
rows are deleted and reinserted); other runs are left alone.
"""
import os
import sys
import json

# Make the `req` package (repo root) and this dir (for `variant`) importable
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
for _p in (_root, _here):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from req._config import open_db
from variant import VariantRequest


class _Run:
    def __init__(self, run_id, model_alias):
        self.run_id = run_id
        self.model_alias = model_alias


class _Resp:
    """Minimal stand-in for PromptResult — only the attributes that
    VariantRequest.process_response / store_result touch."""
    def __init__(self, content):
        self.content = content
        self.error_class = None
        self.error_msg = None
        self.data = None


def _content_of(data):
    try:
        return data['choices'][0]['message']['content'] or ''
    except (KeyError, IndexError, TypeError):
        return ''


def _words_of(payload):
    # VariantRequest.create_prompt sends the words one per line as the user msg
    try:
        prompt = payload['messages'][-1]['content']
    except (KeyError, IndexError, TypeError):
        return []
    return [w for line in prompt.splitlines() for w in (line.strip(),) if w]


def main(run_ids):
    with open_db('w', 'reprocess') as conn:
        models = {r['run_id']: r['model']
                  for r in conn.execute("SELECT run_id, model FROM runs")}

        if run_ids:
            qmarks = ','.join('?' * len(run_ids))
            conn.execute(f"DELETE FROM results WHERE run_id IN ({qmarks})", run_ids)
            raws = conn.execute(
                f"SELECT req_id, run_id, request, response FROM raw_data "
                f"WHERE run_id IN ({qmarks}) ORDER BY req_id", run_ids).fetchall()
        else:
            conn.execute("DELETE FROM results")
            raws = conn.execute(
                "SELECT req_id, run_id, request, response "
                "FROM raw_data ORDER BY req_id").fetchall()

        n_req = 0
        n_rows = 0
        n_notes = 0
        for r in raws:
            payload = json.loads(r['request']) if r['request'] else {}
            data = json.loads(r['response']) if r['response'] else {}

            resp = _Resp(_content_of(data))
            resp.data = data
            run = _Run(r['run_id'], models.get(r['run_id']))
            req = VariantRequest(run, 0, _words_of(payload))

            processed, _notes = req.process_response(resp)
            req.store_result(conn, r['req_id'], resp, processed)

            n_req += 1
            n_rows += len(processed)
            n_notes += sum(1 for row in processed if row.get('notes'))

        total = conn.execute("SELECT count(*) FROM results").fetchone()[0]
        notes_total = conn.execute(
            "SELECT count(*) FROM results WHERE notes IS NOT NULL AND notes <> ''"
        ).fetchone()[0]

    scope = f"runs {run_ids}" if run_ids else "all runs"
    print(f"reprocessed {n_req} requests ({scope})")
    print(f"  parsed variant rows: {n_rows} (with notes: {n_notes})")
    print(f"  results table now: {total} rows, {notes_total} with non-empty notes")


if __name__ == '__main__':
    ids = []
    for a in sys.argv[1:]:
        if not a.isdigit():
            print(f"error: run_id must be an integer: {a}")
            sys.exit(2)
        ids.append(int(a))
    main(ids)
