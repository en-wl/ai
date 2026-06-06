import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import sqlite3
from random import random

from req._loop import STATE_NAMES

class _SerializedHandler(logging.Handler):
    """Logging handler that acquires a shared lock before emitting."""
    def __init__(self, write_lock):
        super().__init__()
        self._write_lock = write_lock

    def emit(self, record):
        try:
            msg = self.format(record)
            with self._write_lock:
                sys.stderr.write(msg + '\n')
                sys.stderr.flush()
        except Exception:
            self.handleError(record)


def run(models, extra_args=(), child_cmd=None):
    from req._config import pre_run, post_run, open_db, CROSS_MODEL_DEPS, STALE_RUNS_TIMEOUT

    if child_cmd is None:
        child_cmd = [sys.executable, '-m', 'req']

    write_lock = threading.Lock()

    log = logging.getLogger()
    handler = _SerializedHandler(write_lock)
    assert(len(log.handlers) == 1)
    old_handler = log.handlers[0]
    handler.setFormatter(old_handler.formatter)
    log.removeHandler(old_handler)
    log.addHandler(handler)

    # Signal handling: 3-stage escalation
    stage = 0
    stage_signal = [None, signal.SIGINT, signal.SIGTERM, signal.SIGKILL]
    stage_exit_code = [0, 1, 3, 4]
    procs = []
    script_proc = None
    stage_lock = threading.Lock()

    def forward_signal(sig, frame):
        nonlocal stage
        with stage_lock:
            if sig == signal.SIGTERM:
                if stage < 2:
                    stage = 2
                    log.warning("SIGTERM received. Sending SIGTERM to all children...")
                elif stage == 2:
                    stage = 3
                    log.warning("Force exit. Sending SIGKILL to all children...")
            else: # SIGINT escalation
                if stage == 0:
                    stage = 1
                    log.warning("Ctrl-C detected. Forwarding SIGINT to all children...")
                    log.info("Press Ctrl-C again to send SIGTERM.")
                elif stage == 1:
                    stage = 2
                    log.warning("Sending SIGTERM to all children...")
                    log.info("Press Ctrl-C again to force kill.")
                else:
                    stage = 3
                    log.warning("Force exit. Sending SIGKILL to all children...")
        sig_to_send = stage_signal[stage]
        targets = list(procs)
        if script_proc is not None:
            targets.append(script_proc)
        for p in targets:
            try:
                p.send_signal(sig_to_send)
            except OSError:
                pass
            

    # Install signal handlers before launching children
    signal.signal(signal.SIGINT, forward_signal)
    signal.signal(signal.SIGTERM, forward_signal)

    # Pre-run script
    if pre_run is not None:
        log.info(f"starting pre-run script: {' '.join(pre_run)}")
        script_proc = subprocess.Popen(pre_run, start_new_session=True)
        rc = script_proc.wait()
        script_proc = None
        if rc != 0:
            log.error(f"pre-run script failed with rc={rc}")
            sys.exit(2)

    # Stale outstanding_runs / outstanding_reqs cleanup
    cutoff = time.time() - STALE_RUNS_TIMEOUT
    with open_db('w') as conn:
        stale_run_ids = [r[0] for r in conn.execute(
            'SELECT run_id FROM outstanding_runs WHERE timestamp < ?', (cutoff,)
        ).fetchall()]
        if stale_run_ids:
            placeholders = ','.join('?' * len(stale_run_ids))
            conn.execute(f'DELETE FROM outstanding_runs WHERE run_id IN ({placeholders})', stale_run_ids)
            conn.execute(f'DELETE FROM outstanding_reqs WHERE run_id IN ({placeholders})', stale_run_ids)
            log.info(f"cleaned up {len(stale_run_ids)} stale outstanding_runs: {stale_run_ids}")
        remaining_runs = conn.execute('SELECT count(*) FROM outstanding_runs').fetchone()[0]
        remaining_reqs = conn.execute('SELECT count(*) FROM outstanding_reqs').fetchone()[0]
    if remaining_runs or remaining_reqs:
        log.error(f"outstanding_runs={remaining_runs}, outstanding_reqs={remaining_reqs} "
                  f"- clean up manually")
        sys.exit(2)

    # Pre-assign run_ids for all children
    with open_db('w') as conn:
        max_runs = conn.execute('SELECT max(run_id) FROM runs').fetchone()[0] or 0
        max_outstanding = conn.execute('SELECT max(run_id) FROM outstanding_runs').fetchone()[0] or 0
        first_run_id = max(max_runs, max_outstanding) + 1
        run_ids = list(range(first_run_id, first_run_id + len(models)))
        now = time.time()
        conn.executemany('INSERT INTO outstanding_runs VALUES (?, ?, ?)',
                         ((rid, now, 'active') for rid in run_ids))

    last_lines = {}

    # Per-child output reader thread
    def reader_thread(proc, model):
        pid = proc.pid
        prefix = f"[{pid}] "
        try:
            for line in proc.stdout:
                for subline in line.splitlines(True):
                    with write_lock:
                        stripped = subline.rstrip('\n')
                        if stripped:
                            last_lines[pid] = stripped
                        sys.stderr.write(prefix + subline)
                        if not subline.endswith('\n'):
                            sys.stderr.write('\n')
                        sys.stderr.flush()
        except Exception:
            pass

    exit_code = 0

    def set_exit_code(rc):
        nonlocal exit_code
        if exit_code < rc:
            exit_code = rc

    proc_thread = {}
    proc_run_id = {}
    for model, run_id in zip(models, run_ids):
        if stage > 0:
            set_exit_code(3)
            break

        cmd = list(child_cmd) + ['--managed', str(run_id), model] + list(extra_args)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        log.info(f"[{proc.pid}] {' '.join(cmd)}")

        t = threading.Thread(target=reader_thread, args=(proc, model), daemon=True)
        t.start()
        proc_thread[proc] = t
        proc_run_id[proc] = run_id
        procs.append(proc)

        # If a signal arrived during launch, forward it to this child
        if stage > 0:
            try:
                proc.send_signal(stage_signal[stage])
            except OSError:
                pass

        delay = 0.2; jitter = 0.1
        time.sleep(delay + random()*jitter - jitter/2)

    # Wait for all children to exit, logging each as it finishes
    import queue
    done_queue = queue.Queue()
    for proc, model in zip(procs, models):
        threading.Thread(target=lambda p, m: (p.wait(), done_queue.put((p, m))),
                         args=(proc, model), daemon=True).start()
    results = {}
    for _ in procs:
        proc, model = done_queue.get()
        proc_thread[proc].join()
        results[proc.pid] = proc.returncode

        rid = proc_run_id.get(proc)
        if rid is not None:
            try:
                with open_db('w') as conn:
                    conn.execute('DELETE FROM outstanding_runs WHERE run_id = ?', (rid,))
                    conn.execute('DELETE FROM outstanding_reqs WHERE run_id = ?', (rid,))
            except sqlite3.DatabaseError:
                pass

    try:
        with open_db('w') as conn:
            conn.executemany('DELETE FROM outstanding_runs WHERE run_id = ?', ((rid,) for rid in run_ids))
            conn.executemany('DELETE FROM outstanding_reqs WHERE run_id = ?', ((rid,) for rid in run_ids))
    except sqlite3.DatabaseError:
        log.warning("failed to clean up, stale outstanding_runs or outstanding_reqs may be left over")

    set_exit_code(stage_exit_code[stage])

    def set_exit_code(rc):
        nonlocal exit_code
        if exit_code < rc:
            exit_code = rc

    # Summary: echo each child's END line
    for proc, model in zip(procs, models):
        last = last_lines.get(proc.pid, '')
                        # *** RUN ABORTED ***: 6/qwen3-235b-a22b: skipped 0 UIDs
        m = re.search(r'\*\*\* RUN ([A-Z]+) \*\*\*: ([^:]+)(.*)$', last)
        if m:
            log.info(f"[{proc.pid}] {m[2]}: {m[1]}{m[3]}")
            rc = results[proc.pid]
            set_exit_code(rc)
        elif results.get(proc.pid, -1) < 0:
            set_exit_code(3)
            log.info(f"[{proc.pid}] {proc_run_id[proc]}/{model}: KILLED (rc={results.get(proc.pid, '?')})")
        else:
            set_exit_code(2)
            log.info(f"[{proc.pid}] {proc_run_id[proc]}/{model}: UNKNOWN (rc={results.get(proc.pid, '?')})")

    # Post-run script
    if post_run is not None and exit_code <= 2:
        stage = 0
        log.info(f"starting post-run script: {' '.join(post_run)}")
        try:
            script_proc = subprocess.Popen(post_run, start_new_session=True)
            rc = script_proc.wait()
            script_proc = None
            if rc != 0:
                set_exit_code(2)
                log.error(f"post-run script failed with rc={rc}")
        except Exception as e:
            set_exit_code(2)
            log.exception("failed to launch post-run script")

    if exit_code < 4:
        # reset the journal_mode to make working with the database file easier
        res = None
        try:
            with open_db(None) as conn:
                res = conn.execute('pragma journal_mode=delete').fetchone()
        except sqlite3.DatabaseError:
            pass
        if res is None or res[0] != 'delete':
            log.warning(f"failed to reset journal mode to 'delete'")

    if exit_code != 0:
        state_name = STATE_NAMES[exit_code] # exit_code must be between 0-4
        log.error(f"** {state_name} **")

    sys.exit(exit_code)
