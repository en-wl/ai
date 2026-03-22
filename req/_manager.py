import sys
import os
import signal
import threading
import logging
import time
import subprocess


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


def run(models, extra_args=()):
    write_lock = threading.Lock()

    # Set up manager logger (no PID — it's the coordinator)
    log = logging.getLogger('req.manager')
    log.propagate = False
    log.setLevel(logging.INFO)
    handler = _SerializedHandler(write_lock)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s.%(msecs)03d: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    log.addHandler(handler)

    # Signal handling: 3-stage escalation
    stage = 0
    procs = []
    stage_lock = threading.Lock()

    def forward_signal(sig, frame):
        nonlocal stage
        with stage_lock:
            if sig == signal.SIGTERM:
                if stage < 2:
                    stage = 2
                    log.info("SIGTERM received. Sending SIGTERM to all children...")
                    for p in procs:
                        try:
                            p.send_signal(signal.SIGTERM)
                        except OSError:
                            pass
                elif stage == 2:
                    stage = 3
                    log.info("Force exit. Sending SIGKILL to all children...")
                    for p in procs:
                        try:
                            p.kill()
                        except OSError:
                            pass
                return

            # SIGINT escalation
            if stage == 0:
                stage = 1
                log.info("Ctrl-C detected. Forwarding SIGINT to all children...")
                log.info("Press Ctrl-C again to send SIGTERM.")
                for p in procs:
                    try:
                        p.send_signal(signal.SIGINT)
                    except OSError:
                        pass
            elif stage == 1:
                stage = 2
                log.info("Sending SIGTERM to all children...")
                log.info("Press Ctrl-C again to force kill.")
                for p in procs:
                    try:
                        p.send_signal(signal.SIGTERM)
                    except OSError:
                        pass
            else:
                stage = 3
                log.info("Force exit. Sending SIGKILL to all children...")
                for p in procs:
                    try:
                        p.kill()
                    except OSError:
                        pass

    # Install signal handlers before launching children
    signal.signal(signal.SIGINT, forward_signal)
    signal.signal(signal.SIGTERM, forward_signal)

    log.info(f"launching {len(models)} models: {', '.join(models)}")

    # Per-child output reader thread
    def reader_thread(proc, model):
        pid = proc.pid
        prefix = f"[{pid}] "
        try:
            for line in proc.stdout:
                for subline in line.splitlines(True):
                    with write_lock:
                        sys.stderr.write(prefix + subline)
                        if not subline.endswith('\n'):
                            sys.stderr.write('\n')
                        sys.stderr.flush()
        except Exception:
            pass

    threads = []
    for model in models:
        cmd = [sys.executable, '-m', 'req', model] + list(extra_args)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        procs.append(proc)
        log.info(f"STARTED: {proc.pid}: {' '.join(cmd)}")

        t = threading.Thread(target=reader_thread, args=(proc, model), daemon=True)
        t.start()
        threads.append(t)

        time.sleep(0.2)

    # Wait for all children to exit, logging each as it finishes
    import queue
    done_queue = queue.Queue()
    for proc, model in zip(procs, models):
        threading.Thread(target=lambda p, m: (p.wait(), done_queue.put((p, m))),
                         args=(proc, model), daemon=True).start()
    results = {}
    for _ in procs:
        proc, model = done_queue.get()
        results[model] = proc.returncode
        log.info(f"EXIT: {proc.pid} ({model}): rc={proc.returncode}")

    # Drain reader threads
    for t in threads:
        t.join(timeout=5)

    # Summary
    failures = {m: rc for m, rc in results.items() if rc != 0}
    if not failures:
        log.info("all models completed successfully")
    else:
        parts = ', '.join(f"{m}(rc={rc})" for m, rc in failures.items())
        log.info(f"completed with errors: {parts}")
        sys.exit(1)
