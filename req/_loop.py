import random
import time
import logging
import signal
from math import ceil, floor
from contextlib import contextmanager
from typing import NamedTuple
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from req._request import Run, abort_event

STATE_NAMES = {0: "FINISHED", 1: "SHUTDOWN", 2: "FAILED", 3: "ABORTED", 4: "KILLED"}

LAST_LOG_INTERVAL = 20

# === request <-> loop contract ===

class RequestResult(NamedTuple):
    failed: set = frozenset()
    redo: set = frozenset()
    completed: set = frozenset()
    error_class: str = None  # '429', 'connection', 'model', or None

# === shutdown machinery ===

last_log_time = None
shutdown_str = ""

def enter_shutdown_mode(reason, prefix=None):
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
        logging.exception(f"ERROR: {e}")
        enter_shutdown_mode("failure mode")

# === signal handling ===

shutdown_requested = False

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

def install_signal_handlers():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

# === generic batch session ===

class BatchSession(Run):
    """Generic scheduler: hands out a shuffled list of items in batches.

    Treats items as opaque — they may be ints (uids), strings (words), etc.
    Subclasses override the policy hooks (threshold / record_result /
    on_request_complete / summary) to add per-item behaviour.
    """
    def __init__(self, model_alias, batch_size, run_id, items):
        super().__init__(model_alias, batch_size, run_id)
        self._todo = list(items)
        random.shuffle(self._todo)

    @property
    def remaining(self):
        return len(self._todo)

    def push(self, *items):
        self._todo.extend(items)

    def _local_batch_size(self):
        # attempt to use equal number of items per request, rather than sending
        # full batches and then one with just a few items
        num_batches = ceil(self.remaining / self.batch_size)
        return floor(self.remaining / num_batches) if num_batches > 0 else 0

    def next(self, seq_id, threshold, in_flight):
        # returns [] only when done; None if there might be more later
        if self.remaining == 0:
            return []
        if self.remaining < threshold:
            return None
        size = self._local_batch_size()
        items = self._todo[-size:]
        del self._todo[-size:]
        return items

    def progress_str(self, seq_id):
        remaining_runs = ceil(self.remaining / self.batch_size)
        return f"#{seq_id}/~{seq_id + remaining_runs}"

    # --- policy hooks (overridden by subclasses) ---

    def threshold(self):
        return 1

    def record_result(self, result):
        """Per-item bookkeeping; returns an adjustment to the other_errors
        counter (default 0)."""
        return 0

    def on_request_complete(self):
        pass

    def summary(self):
        return ''

# === main loop ===

def run_loop(run, request_cls, max_workers):
    global last_log_time

    log_str = (f"*** RUN STARTING ***: {run.run_id}/{run.model_alias}: "
               f"max_workers={max_workers}; batch_size={run.batch_size}")
    logging.info(f"{log_str}; items: {run.remaining}")

    time.sleep(2)

    in_flight = set()
    items_processed = 0
    seq_id = 1
    effective_max_workers = max_workers
    interval = 2
    error_delay = 1
    connection_errors = 0
    other_errors = 0

    def handle_result(future):
        global last_log_time
        nonlocal connection_errors, other_errors
        error_class = None
        with shutdown_mode_on_error():
            result = future.result()
            error_class = result.error_class

            if error_class == 'connection':
                connection_errors += 1
            elif error_class == 'other':
                connection_errors += 1
                other_errors += 1
            elif error_class == 'model':
                other_errors += 1

            # All per-item policy (failure tracking, skip lists, redo) lives
            # in the session; it returns an adjustment to other_errors.
            other_errors += run.record_result(result)

            last_log_time = None
            return len(result.completed), error_class

        return 0, error_class

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Main loop: continue while requests are in flight OR there's work to do
        while True:
            loop_start = time.time()
            completed = 0
            status = set()

            # Process finished requests:
            if len(in_flight) >= effective_max_workers:
                logging.info(f"{shutdown_str}{run.run_id}/{run.model_alias}: {len(in_flight)} requests in flight: waiting for at least one to finish")
                # At capacity: block until at least one request completes
                done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                for f in done:
                    num, err = handle_result(f)
                    completed += num
                    status.add(err)
            else:
                # Poll for completed requests without blocking
                for f in [f for f in in_flight if f.done()]:
                    in_flight.remove(f)
                    num, err = handle_result(f)
                    completed += num
                    status.add(err)

            items_processed += completed

            # Error handling
            backoff = status and ('429' in status or connection_errors >= 2)
            if backoff and error_delay < 30:
                error_delay *= 2
            if status and not (status & {'429', 'connection', 'other'}):
                error_delay = 1
            if status and not (status & {'connection', 'other'}):
                connection_errors = 0
            if None in status or other_errors < 0:
                other_errors = 0

            # Graceful shutdown
            if shutdown_requested:
                enter_shutdown_mode("shutdown requested")
            elif other_errors >= 5:
                enter_shutdown_mode("5 consecutive failures", "failure mode")

            # Post-request hook (e.g. incremental combine)
            if completed:
                with shutdown_mode_on_error():
                    run.on_request_complete()

            # Get next set of items if needed
            if shutdown_str:
                items = []
            elif backoff:
                items = None
            else:
                items = run.next(seq_id, run.threshold(), bool(in_flight))

            # Break when done
            if not in_flight and items == []:
                break

            # Rate Limited handling
            if backoff and items is None:
                wait_time = error_delay + random.random() - 0.5
                elapsed = time.time() - loop_start
                reason = f"{connection_errors} connection errors" if connection_errors >= 2 else 'rate limited'
                logging.info(f"{shutdown_str}{run.run_id}/{run.model_alias}: {reason}, trying again in: {wait_time:.3f}s")
                if elapsed < wait_time:
                    time.sleep(wait_time - elapsed)
                continue

            # Submit new work if any
            if items:
                logging.info(f"starting {run.run_id}/{run.model_alias} {run.progress_str(seq_id)}; items: {len(items)}; req in flight: {len(in_flight) + 1}")
                with shutdown_mode_on_error():
                    f = executor.submit(request_cls(run, seq_id, list(items)).send)
                    seq_id += 1
                    in_flight.add(f)
                    last_log_time = time.time()
            elif in_flight and (last_log_time is None or time.time() - last_log_time >= LAST_LOG_INTERVAL):
                logging.info(f"{shutdown_str}{run.run_id}/{run.model_alias}: {len(in_flight)} requests still pending")
                last_log_time = time.time()
            elif last_log_time is None or time.time() - last_log_time >= LAST_LOG_INTERVAL:
                logging.info(f"{run.run_id}/{run.model_alias}: waiting for other runs to finish")
                last_log_time = time.time()

            # Ensure at least interval (defaults 2) seconds between loop iterations
            elapsed = time.time() - loop_start
            if elapsed < interval:
                time.sleep(interval - elapsed)

    if shutdown_str:
        if abort_event.is_set():
            exit_code = 3  # ABORTED
        elif "failure" in shutdown_str:
            exit_code = 2  # FAILED
        else:
            exit_code = 1  # SHUTDOWN
    else:
        exit_code = 0

    logging.info(f"*** RUN {STATE_NAMES[exit_code]} ***: {run.run_id}/{run.model_alias}: processed {items_processed} total items{run.summary()}")
    return exit_code
