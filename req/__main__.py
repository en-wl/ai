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
        if DYNAMIC_MODE and ENABLE_REDO:
            raise RuntimeError("ENABLE_REDO is not supported in DYNAMIC mode")

        self.input_strings = {}
        self.input_data = {}
        self.dynamic = DYNAMIC_MODE
        self.model_alias = model_alias

        self.header = '|'.join(input_cols)
        with open_db('r') as conn:
            for row in input_rows(conn, model_alias):
                uid = row[0]
                values = [str(col) for col in row]
                self.input_strings[uid] = '|'.join(values)
                self.input_data[uid] = dict(zip(input_cols, row))

        self.batch_size = batch_size

        if self.dynamic:
            self._est_remaining = batch_size
        else:
            self._uids_todo = []
            self.push(*self.input_strings.keys())
            self.shuffle()

        model_config = models_config[model_alias]
        temperature = model_config.get('temperature', 1) if temp_override is None else temp_override
        reasoning = model_config.get('reasoning', 'n/a')

        with open_db('w') as conn:
            cur = conn.execute(
                """INSERT INTO runs (model, start_time, batch_size, temperature, reasoning_effort, sample_type)
                   VALUES (?, (julianday('now') - 2440587.5) * 86400.0, ?, ?, ?, 'random')""",
                (model_alias, self.batch_size, temperature, reasoning)
            )
            self.run_id = cur.lastrowid

    @property
    def remaining(self):
        if self.dynamic:
            return self._est_remaining
        return len(self._uids_todo)

    def push(self, *uids):
        for uid in uids:
            if uid in bad_uids:
                continue
            self._uids_todo.append(uid)

    def shuffle(self):
        random.shuffle(self._uids_todo)

    def _local_batch_size(self):
        num_batches = ceil(self.remaining / self.batch_size)
        return floor(self.remaining / num_batches) if num_batches > 0 else 0

    def next(self, seq_id, threshold = -1):
        if self.dynamic:
            return self._next_dynamic(seq_id, threshold)
        if self.remaining < threshold:
            return None
        size = self._local_batch_size()
        uids = self._uids_todo[-size:]
        del self._uids_todo[-size:]
        return uids

    def _next_dynamic(self, seq_id, threshold):
        with open_db('w') as conn:
            create_candidates_temp_table(conn, self.model_alias, self.run_id)
            conn.execute('''
                CREATE TEMP TABLE _candidates_w_outstanding AS
                SELECT c.uid, c.word, c.pos,
                       c.reqs_cnt + coalesce(o.cnt, 0) AS reqs_cnt,
                       c.num - coalesce(o.cnt, 0) AS num
                  FROM _candidates c
                  LEFT JOIN (SELECT uid, count(*) AS cnt
                               FROM outstanding_reqs WHERE model = ?
                               GROUP BY uid) o USING (uid)
                  WHERE c.num - coalesce(o.cnt, 0) > 0
                    AND c.uid NOT IN (SELECT uid FROM skipped_uids WHERE run_id = ?)
                ''', (self.model_alias, self.run_id))
            self._est_remaining = conn.execute('SELECT sum(num) FROM _candidates_w_outstanding').fetchone()[0] or 0
            if self._est_remaining < threshold:
                return None
            uids = [r[0] for r in conn.execute('SELECT uid FROM _candidates_w_outstanding ORDER BY reqs_cnt, num DESC, random() LIMIT ?',
                                               (self._local_batch_size(),))]
            now = time.time()
            conn.executemany('INSERT INTO outstanding_reqs VALUES (?,?,?,?,?)',
                             ((uid, self.model_alias, self.run_id, seq_id, now) for uid in uids))
            self._est_remaining -= len(uids)
        return uids

    def progress_str(self, seq_id):
        remaining_runs = ceil(self.remaining / self.batch_size)
        return f"#{seq_id}/~{seq_id + remaining_runs}"

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
    if not run.remaining:
        return False
    if run.dynamic:
        logging.info(f"STARTING RUN {run.run_id}/{model_alias}")
    else:
        logging.info(f"STARTING RUN {run.run_id}/{model_alias}; UIDs: {run.remaining}")

    in_flight = set()
    seq_id = 1
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
        last_log_time = None

    def handle_result(future):
        global consecutive_errors
        nonlocal effective_max_workers, last_log_time
        try:
            result = future.result()
        except Exception as e:
            logging.exception(f"ERROR: {e}")
            enter_shutdown_mode("failure mode")
            return

        failed = result.failed
        redo = result.redo
        completed = result.completed
        hit_429 = result.hit_429
        error_class = result.error_class

        if shutdown_str:
            return

        if hit_429 and record_rate_limit():
            old = effective_max_workers
            effective_max_workers = max(1, min(len(in_flight), old-1))
            if effective_max_workers < old:
                logging.warning(f"*** RATE LIMITED: max_workers capped {old} -> {effective_max_workers} ***")
            elif effective_max_workers == 1:
                consecutive_errors += 1
            if not run.dynamic:
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

            if run.dynamic:
                with open_db('w') as conn:
                    conn.executemany(
                        'INSERT OR IGNORE INTO skipped_uids VALUES (?,?)',
                        [(uid, run.run_id) for uid in new_bad_uids])

        if ENABLE_REDO:  # guaranteed not dynamic (checked in __init__)
            run.push(*redo)

        # Incremental combine (dynamic mode)
        if run.dynamic:
            if on_request_complete is not None:
                on_request_complete()

        last_log_time = None


    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Main loop: continue while requests are in flight OR there's work to do
        while True:
            loop_start = time.time()

            # Process finished requests:
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
            
            # Graceful shutdown
            if shutdown_requested:
                enter_shutdown_mode("shutdown requested")
            elif consecutive_errors >= 5:
                enter_shutdown_mode("5 consecutive failures", "failure mode")

            # Get next set of UIDs if needed
            if shutdown_str:
                uids = None
            elif not in_flight:
                uids = run.next(seq_id)
            elif ENABLE_REDO:
                uids = run.next(seq_id, threshold=batch_size)
            elif run.dynamic:
                uids = run.next(seq_id, threshold=ceil(batch_size/2))
            else:
                uids = run.next(seq_id)

            # Break when done
            if not in_flight and not uids:
                break

            # Submit new work if any
            if uids:
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

    # Parse: model ... [<num>] [<num>]
    # A model is anything not starting with a digit or '-'
    i = 0
    models = []
    while i < len(args) and not (args[i][:1].isdigit() or args[i][:1] == '-'):
        models.append(args[i])
        i += 1

    max_workers = 100
    batch_size_override = None
    rest = []
    if i < len(args):
        try:
            max_workers = int(args[i])
        except ValueError:
            print(f"error: invalid max_workers value: {args[i]}")
            sys.exit(2)
        rest.append(args[i])
        i += 1
    if i < len(args) and (args[i][:1].isdigit() or args[i][:1] == '-'):
        try:
            batch_size_override = int(args[i])
        except ValueError:
            print(f"error: invalid batch_size value: {args[i]}")
            sys.exit(2)
        rest.append(args[i])
        i += 1

    if i < len(args):
        print(f"error: unexpected extra arguments: {' '.join(args[i:])}")
        print(f"usage: python3 -m req <model> [model2 ...] [max_workers] [batch_size]")
        sys.exit(2)

    bad = [m for m in models if m not in models_config]
    if bad:
        print(f"error: unknown model(s): {', '.join(bad)}")
        print(f"available models: {', '.join(models_config.keys())}")
        sys.exit(2)

    if not models:
        print(f"error: no model specified")
        print(f"available models: {', '.join(models_config.keys())}")
        sys.exit(2)

    with open_db('w') as conn:
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

        if DYNAMIC_MODE:
            main(max_workers, batch_size)

        else:
            cont = True
            while True:
                if post_run is not None:
                    subprocess.run(post_run, check=True)
                if not cont:
                    break
                cont = main(max_workers, batch_size)
                if ENABLE_REDO:
                    cont = False

        logging.info(f"END: {model_alias}: {STATE_NAMES[exit_code]}; skipped {len(bad_uids)} UIDs")
        sys.exit(exit_code)
