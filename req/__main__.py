import sqlite3
import random
from math import ceil,floor
import os
import time
import logging
import sys
import signal
import subprocess

from req._config import *
from req._request import *

STATE_NAMES = {0: "FINISHED", 1: "SHUTDOWN", 2: "FAILED", 3: "ABORTED"}
exit_code = 0

bad_uids = set()
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
        self._uids_todo = []
        self.push(*self.input_strings.keys())
        self.shuffle()

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

    def todo_size(self):
        return len(self._uids_todo)

    def clear_todo(self):
        self._uids_todo.clear()

    def push(self, *uids):
        for uid in uids:
            if uid in bad_uids:
                continue
            self._uids_todo.append(uid)

    def shuffle(self):
        random.shuffle(self._uids_todo)

    def next(self):
        self.num_batches = ceil(len(self._uids_todo) / self.batch_size)
        size = floor(len(self._uids_todo) / self.num_batches) if self.num_batches > 0 else 0
        uids = self._uids_todo[-size:]
        del self._uids_todo[-size:]
        return uids

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

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

    if sig == signal.SIGTERM:
        # SIGTERM goes straight to abort phase
        if not shutdown_requested:
            shutdown_requested = True
        if not abort_event.is_set():
            logging.info("\nSIGTERM received. Aborting current requests...")
            logging.info("Send again to force immediate exit.")
            abort_event.set()
        else:
            logging.info("\nForce exit requested. Exiting immediately.")
            os._exit(128 + sig)
        return

    if interrupt_count == 1:
        logging.info("\nCtrl-C detected. Finishing current requests and shutting down gracefully...")
        logging.info("Press Ctrl-C again to abort current requests.")
        shutdown_requested = True
    elif interrupt_count == 2:
        logging.info("\nAborting current requests. Press Ctrl-C again to force exit.")
        abort_event.set()
    else:
        logging.info("\nForce exit requested. Exiting immediately.")
        os._exit(128 + sig)

failed_uids = {}
consecutive_errors = 0
model_alias = None
def main(max_workers, batch_size):
    run = BatchSession(model_alias, batch_size)
    if not run.todo_size():
        return False
    logging.info(f"STARTING RUN {run.run_id}/{model_alias}; UIDs: {run.todo_size()}")

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
        run.clear_todo()
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
            run.push(*redo)
            return

        # Consecutive systematic/connection error tracking
        if error_class is None:
            consecutive_errors = 0
        else:
            consecutive_errors += 1

        # Reset failure count for UIDs that succeeded
        for uid in completed:
            failed_uids.pop(uid, None)

        # Track per-UID failures (always active)
        for uid in failed:
            failed_uids[uid] = failed_uids.get(uid, 0) + 1
        new_bad_uids = {uid for uid, cnt in failed_uids.items() if cnt >= 3}
        if new_bad_uids:
            bad_uids.update(new_bad_uids)
            for uid in new_bad_uids:
                del failed_uids[uid]
            sorted_uids = sorted(new_bad_uids)
            if len(sorted_uids) > 8:
                uids_str = ','.join(str(u) for u in sorted_uids[:7]) + ',…'
            else:
                uids_str = ','.join(str(u) for u in sorted_uids)
            logging.warning(f"{model_alias}: SKIPPING {len(new_bad_uids)} UIDs (3+ consecutive failures): {uids_str}")
            # reset consecutive_errors as the errors may of been due to specific UIDS.
            consecutive_errors = 0

        # Requeue
        if ENABLE_REDO:
            run.push(*redo)

        last_log_time = None


    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Main loop: continue while requests are in flight OR there's work to do
        while in_flight or run.todo_size():
            loop_start = time.time()

            if len(in_flight) >= effective_max_workers:
                logging.info(f"{shutdown_str}{run.run_id}/{model_alias}: {len(in_flight)} requests in flight: waiting for at least one to finish")
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
            elif consecutive_errors >= 5:
                enter_shutdown_mode("5 consecutive failures", "failure mode")

            # Submit new work if:
            #   - there's work to do, AND
            #   - redo is disabled (submit any size batch), OR
            #   - we have a full batch worth of work, OR
            #   - nothing in flight (submit final partial batch)
            if run.todo_size() and (not ENABLE_REDO or run.todo_size() >= batch_size or not in_flight):
                uids = run.next()
                f = executor.submit(send_request, run, model_alias, seq_id, list(uids))
                seq_id += 1
                in_flight.add(f)
                last_log_time = time.time()
            elif in_flight and (last_log_time is None or time.time() - last_log_time >= LAST_LOG_INTERVAL):
                logging.info(f"{shutdown_str}{run.run_id}/{model_alias}: {len(in_flight)} requests still pending")
                last_log_time = time.time()

            # Ensure at least 2 seconds between loop iterations
            elapsed = time.time() - loop_start
            if elapsed < 2:
                time.sleep(2 - elapsed)

        if shutdown_str:
            logging.info(f"ABORTED RUN {run.run_id}/{model_alias}")
            global exit_code
            if abort_event.is_set():
                exit_code = max(exit_code, 3)  # ABORTED
            elif "failure" in shutdown_str:
                exit_code = max(exit_code, 2)  # FAILED
            else:
                exit_code = max(exit_code, 1)  # SHUTDOWN
            return None

    logging.info(f"COMPLETED RUN {run.run_id}/{model_alias}")
    return True

if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print(f"usage: python3 -m req <model> [model2 ...] [max_workers] [batch_size]")
        print(f"\navailable models: {', '.join(models_config.keys())}")
        sys.exit(2)

    models = [a for a in args if a in models_config]
    rest = [a for a in args if a not in models_config]
    max_workers = 100
    batch_size_override = None
    if rest and rest[0] != '-':
        max_workers = int(rest[0])
    if len(rest) > 1:
        batch_size_override = int(rest[1])

    if not models:
        print(f"error: no valid model specified")
        print(f"available models: {', '.join(models_config.keys())}")
        sys.exit(2)

    with sqlite3.connect(db) as conn:
        conn.executemany("insert or ignore into models values (?)",
                         ((k,) for k in models_config.keys()))

    if len(models) > 1:
        from req._manager import run as manager_run
        manager_run(models, extra_args=rest)
    else:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        model_alias = models[0]
        batch_size = batch_size_override or models_config[model_alias]['batch_size']

        logging.info(f"BEGIN: {model_alias}: max_workers={max_workers}; batch_size={batch_size}")
        time.sleep(2)

        cont = True
        while True:
            if post_run is not None:
                subprocess.run(post_run, check=True)
            if not cont:
                break
            cont = main(max_workers, batch_size)

        logging.info(f"END: {model_alias}: {STATE_NAMES[exit_code]}; skipped {len(bad_uids)} UIDs")
        sys.exit(exit_code)
