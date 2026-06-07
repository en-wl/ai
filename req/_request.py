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

class Run:
    def __init__(self, model_alias, batch_size, run_id = None):
        self.model_alias = model_alias
        self.run_id = run_id

        self.batch_size = batch_size

        model_config = models_config[model_alias]
        temperature = model_config.get('temperature', 1) if temp_override is None else temp_override
        reasoning = model_config.get('reasoning', 'n/a')
        provider = model_config.get('provider')

        with open_db('w', 'batch init') as conn:
            cur = conn.execute(
                """INSERT INTO runs (run_id, model, provider, start_time, batch_size, temperature, reasoning_effort, sample_type)
                   VALUES (?, ?, ?, (julianday('now') - 2440587.5) * 86400.0, ?, ?, ?, 'random')""",
                (run_id, model_alias, provider, batch_size, temperature, reasoning)
            )
            if run_id is None:
                self.run_id = cur.lastrowid


# Thread safety: send_request() runs in a ThreadPoolExecutor from __main__.py,
# so all code in this module must be safe for concurrent execution.  This works
# because every function uses only local variables and read-only module-level
# config imported from _config.  The one shared mutable resource (the SQLite
# database) is accessed through short-lived per-call connections, which SQLite
# serializes internally.

abort_event = threading.Event()

class RetryNoTimeout(Retry):
    """Retry on status/connection errors but not on timeouts."""
    def increment(self, method=None, url=None, response=None, error=None, **kwargs):
        if isinstance(error, urllib3.exceptions.TimeoutError):
            raise error
        return super().increment(method=method, url=url, response=response,
                                 error=error, **kwargs)

@dataclass(slots = True)
class PromptResult:
    payload: dict
    send_time: float
    data: dict = field(default_factory=dict)
    content: str = ''
    error_class: str = None
    error_msg: str = None

# Standard server errors: 500, 502, 503, 504
# Cloudflare errors: 520, 521, 522, 524
status_codes_to_retry = [500, 502, 503, 504, 520, 521, 522, 524]
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

def send_prompt(model_alias, prompt):
    model = models_config[model_alias]
    model_id = model['name']
    provider_name = model.get('provider')
    p = providers[provider_name]

    payload = {
        "model": model_id,
        "stream": True,
        "messages": [
            {"role": "system", "content": model_specific_instructions(model)},
            {"role": "user", "content": prompt},
        ],
    }

    if provider_name is None:
        payload["provider"] = {"only": model['providers']}

    if temp_override is not None:
       payload['temperature'] = temp_override
    elif 'temperature' in model:
       payload['temperature'] = model['temperature']
       if 'top_p' in model:
           payload['top_p'] = model['top_p']

    reasoning = model.get('reasoning', None)
    if reasoning is not None:
        if provider_name is None:
            payload["reasoning"] = {
                "effort": reasoning,
                "summary": "concise",
                #"max_tokens": 4000,
            }
        else:
            payload["reasoning_effort"] = reasoning

    if 'verbosity' in model:
        payload['verbosity'] = model['verbosity']

    if 'service_tier' in model:
        payload['service_tier'] = model['service_tier']

    max_output = model.get('max_output', None)
    if max_output is not None:
        payload['max_output'] = max_output

    stop_text = model.get("stop", None)
    if stop_text is not None:
        payload['stop'] = stop_text

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
    )
    http_session = requests.Session()
    http_session.mount("https://", adapter)

    cfg = models_config[model_alias]
    timeout = cfg.get('timeout', 30)

    resp = None
    have_data = False
    r = PromptResult(payload, time.time())
    try:
        resp = http_session.post(p['url'], headers=p['headers'], json=payload, timeout=timeout, stream=True)
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
            if not r.data:
                last_data_time = now
                r.data = chunk.copy()
                r.data['object'] = 'reconstructed'
                message = {
                    'content': ''
                }
                r.data['choices'] = [{
                    'message': message
                }]

            if chunk['choices']:
                choice_data = chunk['choices'][0]
                have_data = True
            else:
                choice_data = {}

            for key, value in choice_data.get('delta', {}).items():
                if key in ('content', 'reasoning', 'reasoning_content') and value:
                    last_data_time = now
                    message[key] = message.get(key, '') + value
                elif key in ('reasoning_details'):
                    # fixme: merge
                    pass

            if choice_data.get('finish_reason', None) is not None:
                r.data['choices'][0]['finish_reason'] = choice_data['finish_reason']
                r.data['choices'][0]['native_finish_reason'] = choice_data.get('native_finish_reason', None)

            error = chunk.get('error', None)
            if error:
                r.error_msg = error.get('message', str(error))
                r.data['error'] = error

            usage = chunk.get('usage', None)
            if usage is not None:
                have_data = True
                last_data_time = now
                r.data['usage'] = usage

            if now - last_data_time > timeout:
                raise requests.exceptions.Timeout(f"No data received for {timeout}s")

            if abort_event.is_set():
                # logging.info(f"aborting: {run.run_id}/{model_alias} #{seq_id}")
                break

    except requests.HTTPError as e:
        r.error_msg = f"{type(e).__name__}: {e}"
        r.error_class = 'connection'
        if e.response is None:
            r.data = {"error": r.error_msg}
        else:
            resp = e.response
            if resp.status_code == 429:
                r.error_class = '429'
            r.data = {"error": r.error_msg,
                    "status_code": resp.status_code,
                    "reason": resp.reason,
                    "headers": {k:v for k,v in resp.headers.items()},
                    "body": resp.text}
    except (requests.exceptions.Timeout, urllib3.exceptions.TimeoutError) as e:
        r.error_msg = f"{type(e).__name__}: {e}"
        r.data['error'] = r.error_msg
    except Exception as e:
        logging.exception(e)
        r.error_msg = f"{type(e).__name__}: {e}"
        r.data["error"] = r.error_msg
    if r.error_msg and not r.error_class:
        if have_data:
            r.error_class = 'other'
        else:
            r.error_class = 'connection'

    try:
        r.content = r.data["choices"][0]["message"]["content"] or '' # to guard against None value
    except (KeyError, IndexError, TypeError):
        pass

    return r

class Request:
    def __init__(self, run, seq_id, data):
        self.run = run
        self.model_alias = run.model_alias
        self.seq_id = seq_id
        self.data = data

    def create_prompt(self):
        return ''.join(f"{line}\n" for line in self.data)

    def process_response(self, response):
        return response, None

    def store_result(self, conn, req_id, response, processed):
        return processed, None

    def batch_size(self):
        return len(self.data)

    def send(self):
        prompt = self.create_prompt()
        response = send_prompt(self.model_alias, prompt)
        processed, model_notes = self.process_response(response)

        while True:
            try:
                with open_db('w', 'results') as conn:
                    cur = conn.execute(
                        """INSERT INTO requests (entry_time, send_time, run_id, batch_size, error, model_notes)
                           VALUES ((julianday('now') - 2440587.5) * 86400.0, ?, ?, ?, ?, ?)""",
                        (response.send_time, self.run.run_id, self.batch_size(),
                         response.error_msg, model_notes))
                    req_id = cur.lastrowid
                    conn.execute(
                        "INSERT INTO raw_data (req_id, run_id, request, response) VALUES (?, ?, ?, ?)",
                        (req_id, self.run.run_id, json.dumps(response.payload), json.dumps(response.data)))
                    ret, msg = self.store_result(conn, req_id, response, processed)
                    break
            except sqlite3.OperationalError as e:
                if "locked" not in str(e):
                    raise
                logging.info(f"SQLite locked for {self.model_alias} #{self.seq_id}: {e}. Retrying...")
                time.sleep(5)

        if msg:
            logging.info(msg)
        return ret
