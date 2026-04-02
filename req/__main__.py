import random
from math import ceil,floor
import os
import time
import logging
import sys
import signal

from req._config import *
from req._request import *
from req._manager import STATE_NAMES,  run as manager_run

last_log_time = None
shutdown_str = ""
def enter_shutdown_mode(reason, prefix = None):
    global shutdown_str, last_log_time
    if shutdown_str:
        return
    if prefix is None:
        prefix = reason
    logging.warning(f"*** ENTERING SHUTDOWN MODE: {reason} ***")
    shutdown_str = f"{prefix}: "
    last_log_time = None

@contextmanager
def shutdown_mode_on_error():
    try:
        yield None
    except Exception as e:
        logging.error(f"ERROR: {e}")
        enter_shutdown_mode("failure mode")

bad_uids = set()
class BatchSession:
    def __init__(self, model_alias, batch_size, run_id):
        if DYNAMIC_MODE and ENABLE_REDO:
            raise RuntimeError("ENABLE_REDO is not supported in DYNAMIC mode")

        self.input_strings = {}
        self.input_data = {}
        self.dynamic = DYNAMIC_MODE
        self.model_alias = model_alias
        self.run_id = run_id

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

        with open_db('w', 'batch init') as conn:
            conn.execute(
                """INSERT INTO runs (run_id, model, start_time, batch_size, temperature, reasoning_effort, sample_type)
                   VALUES (?, ?, (julianday('now') - 2440587.5) * 86400.0, ?, ?, ?, 'random')""",
                (run_id, model_alias, self.batch_size, temperature, reasoning)
            )

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
        # attempt to use equal number of uids per request, rather than sending
        # full batches and then one with just a few uids
        num_batches = ceil(self.remaining / self.batch_size)
        return floor(self.remaining / num_batches) if num_batches > 0 else 0

    def next(self, seq_id, threshold, in_flight):
        # only returns an empty list when done
        # returns None if there might be more uids to process
        if self.dynamic:
            return self._next_dynamic(seq_id, threshold, in_flight)
        if self.remaining == 0:
            return []
        if self.remaining < threshold:
            return None
        size = self._local_batch_size()
        uids = self._uids_todo[-size:]
        del self._uids_todo[-size:]
        return uids

    def _next_dynamic(self, seq_id, threshold, in_flight):
        assert(threshold > 0)
        with shutdown_mode_on_error(), open_db('w', 'candidates') as conn:
            create_candidates_temp_table(conn, self.model_alias, self.run_id)
            conn.execute('''
                CREATE TEMP TABLE _candidates_w_outstanding AS
                SELECT c.uid,
                       c.reqs_cnt + coalesce(o.cnt, 0) AS reqs_cnt,
                       c.num - coalesce(o.cnt, 0) AS num
                  FROM _candidates c
                  LEFT JOIN (SELECT uid, count(*) AS cnt
                               FROM outstanding_reqs WHERE model = ?
                               GROUP BY uid) o USING (uid)
                  WHERE c.num - coalesce(o.cnt, 0) > 0
                    AND c.uid NOT IN (SELECT uid FROM skipped_uids WHERE run_id = ?)
                ''', (self.model_alias, self.run_id))
            num_uids, min_reqs, self._est_remaining = conn.execute(
                'SELECT count(*), COALESCE(MAX(num),0), COALESCE(sum(NUM),0) FROM _candidates_w_outstanding').fetchone()
            work_to_do = num_uids >= threshold # or min_reqs > 1
            now = time.time()
            def state():
                return conn.execute("SELECT state from outstanding_runs where run_id = ?", (self.run_id,)).fetchone()[0]
            def update_state(state):
                conn.execute("UPDATE outstanding_runs SET state = ?, timestamp = ? WHERE run_id = ?", (state, now, self.run_id,))
            def get_uids():
                update_state('active')
                uids = [r[0] for r in conn.execute('SELECT uid FROM _candidates_w_outstanding ORDER BY reqs_cnt, num DESC, random() LIMIT ?',
                                                   (self._local_batch_size(),))]
                conn.executemany('INSERT INTO outstanding_reqs VALUES (?,?,?,?,?)',
                                 ((uid, self.model_alias, self.run_id, seq_id, now) for uid in uids))
                self._est_remaining -= len(uids)
                return uids
            if in_flight and not work_to_do:
                return None
            if not CROSS_MODEL_DEPS:
                return get_uids()
            if num_uids != 0:
                # not done
                conn.execute("UPDATE outstanding_runs SET state = 'waiting', timestamp = ? where state = 'done'", (now,))
            if work_to_do:
                return get_uids()
            def wakeup():
                if num_uids == 0:
                    any_active = conn.execute("SELECT MAX(state = 'active') from outstanding_runs").fetchone()[0]
                    if any_active:
                        update_state('waiting')
                    else:
                        update_state('done')
                    return None
                return get_uids()
            if state() == 'wakeup':
                return wakeup()
            all_done = conn.execute("SELECT MIN(state = 'done') from outstanding_runs").fetchone()[0]
            if all_done:
                # trully done
                return []
            update_state('waiting')
            all_waiting = conn.execute("SELECT MIN(state = 'waiting') from outstanding_runs").fetchone()[0]
            if all_waiting:
                conn.execute("UPDATE outstanding_runs SET state = 'wakeup', timestamp = ?", (now,))
                return wakeup()
            return None
        return []

    def progress_str(self, seq_id):
        remaining_runs = ceil(self.remaining / self.batch_size)
        return f"#{seq_id}/~{seq_id + remaining_runs}"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

shutdown_requested = False

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
    logging.info("rate limit hit: {len(rate_limit_hits)}")
    return len(rate_limit_hits) >= RATE_LIMIT_THRESHOLD

def signal_handler(sig, frame):
    global shutdown_requested
    shutdown_requested = True
    if abort_event.is_set():
        logging.warning("Aborting current requests...")
    elif sig == signal.SIGTERM:
        logging.warning("SIGTERM received. Aborting current requests...")
        abort_event.set()
    else:
        logging.warning("Ctrl-C detected. Finishing current requests and shutting down gracefully...")

failed_uids = {}
consecutive_errors = 0
model_alias = None

def main(max_workers, batch_size, run_id):
    global last_log_time
    run = BatchSession(model_alias, batch_size, run_id)

    log_str = f"*** RUN STARTING ***: {run.run_id}/{model_alias}: max_workers={max_workers}; batch_size={batch_size}"
    if run.dynamic:
        logging.info(log_str)
    else:
        logging.info(f"{log_str}; UIDs: {run.remaining}")

    time.sleep(2)

    in_flight = set()
    seq_id = 1
    effective_max_workers = max_workers

    LAST_LOG_INTERVAL = 20

    def handle_result(future):
        global consecutive_errors, last_log_time
        nonlocal effective_max_workers
        with shutdown_mode_on_error():
            result = future.result()

            if shutdown_str:
                return 0

            failed = result.failed
            redo = result.redo
            completed = result.completed
            error_class = result.error_class

            # Rate limit and consecutive systematic/connection error tracking
            if error_class == '429' and record_rate_limit():
                old = effective_max_workers
                effective_max_workers = max(1, min(len(in_flight), old-1))
                if effective_max_workers < old:
                    logging.warning(f"*** RATE LIMITED: max_workers capped {old} -> {effective_max_workers} ***")
                elif effective_max_workers == 1:
                    consecutive_errors += 1
            elif error_class is None:
                consecutive_errors = 0
            elif error_class != '429':
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
                logging.info(f"{model_alias}: SKIPPING {len(new_bad_uids)} UIDs (3+ consecutive failures): {uids_str}")
                # reset consecutive_errors as the errors may of been due to specific UIDS.
                consecutive_errors = 0

                if run.dynamic:
                    with open_db('w', 'skipped uids') as conn:
                        conn.executemany(
                            'INSERT OR IGNORE INTO skipped_uids VALUES (?,?)',
                            [(uid, run.run_id) for uid in new_bad_uids])

            if not run.dynamic and (error_class == '429' or ENABLE_REDO):
                run.push(*redo)

            last_log_time = None
            return len(completed)

        return 0


    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Main loop: continue while requests are in flight OR there's work to do
        while True:
            loop_start = time.time()
            completed = 0

            # Process finished requests:
            if len(in_flight) >= effective_max_workers:
                logging.info(f"{shutdown_str}{run.run_id}/{model_alias}: {len(in_flight)} requests in flight: waiting for at least one to finish")
                # At capacity: block until at least one request completes
                done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                for f in done:
                    completed += handle_result(f)
            else:
                # Poll for completed requests without blocking
                for f in [f for f in in_flight if f.done()]:
                    in_flight.remove(f)
                    completed += handle_result(f)

            # Graceful shutdown
            if shutdown_requested:
                enter_shutdown_mode("shutdown requested")
            elif consecutive_errors >= 5:
                enter_shutdown_mode("5 consecutive failures", "failure mode")

            # Incremental combine (dynamic mode)
            if run.dynamic and completed and on_request_complete is not None:
                with shutdown_mode_on_error():
                    on_request_complete()

            # Get next set of UIDs if needed
            if shutdown_str:
                uids = []
            else:
                threshold = (batch_size if ENABLE_REDO else
                             ceil(batch_size/2) if run.dynamic else
                             1)
                uids = run.next(seq_id, threshold, bool(in_flight))

            # Break when done
            if not in_flight and uids == []:
                break

            # Submit new work if any
            if uids:
                logging.info(f"starting {run.run_id}/{model_alias} {run.progress_str(seq_id)}; UIDs: {len(uids)}; req in flight: {len(in_flight) + 1}")
                with shutdown_mode_on_error():
                    f = executor.submit(send_request, run, model_alias, seq_id, list(uids))
                    seq_id += 1
                    in_flight.add(f)
                    last_log_time = time.time()
            elif in_flight and (last_log_time is None or time.time() - last_log_time >= LAST_LOG_INTERVAL):
                logging.info(f"{shutdown_str}{run.run_id}/{model_alias}: {len(in_flight)} requests still pending")
                last_log_time = time.time()
            elif last_log_time is None or time.time() - last_log_time >= LAST_LOG_INTERVAL:
                logging.info(f"{run.run_id}/{model_alias}: waiting for other runs to finish")
                last_log_time = time.time()

            # Ensure at least 2 seconds between loop iterations
            elapsed = time.time() - loop_start
            if elapsed < 2:
                time.sleep(2 - elapsed)

    if shutdown_str:
        if abort_event.is_set():
            exit_code = 3  # ABORTED
        elif "failure" in shutdown_str:
            exit_code = 2  # FAILED
        else:
            exit_code = 1  # SHUTDOWN
    else:
        exit_code = 0

    logging.info(f"*** RUN {STATE_NAMES[exit_code]} ***: {run.run_id}/{model_alias}: skipped {len(bad_uids)} UIDs")
    return exit_code

if __name__ == '__main__':
    args = sys.argv[1:]
    managed = False
    run_id = None
    if args and args[0] == '--managed':
        managed = True
        args = args[1:]
        if not args or not args[0][:1].isdigit():
            print("error: --managed requires a run_id argument")
            sys.exit(2)
        run_id = int(args[0])
        args = args[1:]
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

    if not managed:
        manager_run(models, extra_args=rest)
    else:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        model_alias = models[0]
        batch_size = batch_size_override or models_config[model_alias]['batch_size']

        rc = main(max_workers, batch_size, run_id)
        sys.exit(rc)
