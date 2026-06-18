from pathlib import Path
import os, sys

_dir = _config_dir
if str(_dir) not in sys.path:
    sys.path.insert(0, str(_dir))

SLOW_QUERY_THRESHOLD = 0.35

mode = os.getenv('REQ_MODE')
if mode not in ('ONCE', 'DYNAMIC'):
    raise ValueError('REQ_MODE env var must be defined and one of ONCE DYNAMIC')

x_title = 'Plural Classification'
key_file = '/home/kevina/wordlist/keys/openrouter.txt'

# Allow offline tests to bypass the keys dir.  _config.py honors REQ_KEY_FILE
# for the OpenRouter key; gpt-oss-120b (provider=deepinfra) also forces a read
# of deepinfra_key_file on import, so mirror that override here.
deepinfra_key_file = os.environ.get('REQ_DEEPINFRA_KEY_FILE', deepinfra_key_file)

for k, v in models_config.items():
    v['reasoning'] = "none"
models_config["gpt-oss-120b"]["reasoning"] = "low"

categories = {'natural', 'contrived', 'ungrammatical', 'gerund', 'invalid'}

# Final category tally; runs once after the batch finishes (both modes).
post_run = ['python3', str(_dir / 'combine.py')]

# Per-model consensus thresholds: (min_runs, max_runs).  Request each uid at
# least min_runs times; if its category votes are still not unanimous, escalate
# up to max_runs.  Add per-model exceptions here -- this is the single source of
# truth for the threshold logic.
CONSENSUS_THRESHOLDS = {
    None:          (3, 5),    # default
    'gemma-4-31b': (5, 10),
}

def _thresholds(model):
    return CONSENSUS_THRESHOLDS.get(model, CONSENSUS_THRESHOLDS[None])

ENABLE_REDO = True if mode == 'ONCE' else False

if mode == 'ONCE':
    def input_rows(conn, model):
        return conn.execute('select * from input')
else:  # DYNAMIC
    DYNAMIC_MODE = True
    CROSS_MODEL_DEPS = False   # within-model consensus only

    _candidates_sql = (_dir / 'candidates-dynamic.sql.in').read_text()

    def create_candidates_temp_table(conn, model, run_id):
        min_runs, max_runs = _thresholds(model)
        conn.execute(_candidates_sql,
                     {'model': model, 'min_runs': min_runs, 'max_runs': max_runs})

    def input_rows(conn, model):
        return conn.execute('select * from input')

    # on_request_complete left None: the candidates query reads results_w_model
    # directly, so no incremental combine is needed during the run.


def validate_row(row, input_row):
    len_row = len(row)
    assert row._expected == 4
    len_diff = len_row - 4

    # Light row repair
    new_row = None
    if len_diff == -1:
        # notes column omitted; pad with empty string
        new_row = row._make((*row, ''))
    elif len_diff > 0:
        # collapse a trailing adjacent duplicate cell
        for i in range(len_row - 1, 0, -1):
            if row[i] == row[i - 1]:
                new_row = row._make((*row[:i], *row[i + 1:]))
                break
    if new_row is not None:
        new_row, err = validate_row(new_row, input_row)
        if err is None:
            return new_row, err
    if len_diff != 0:
        # can't fix row; let framework flag MALFORMED_ROW
        return row, None

    # Verify echoed plural is a verbatim copy of the input plural
    if row.plural != input_row['plural']:
        return row, {'error_code': 'PLURAL_MISMATCH',
                     'error_msg': f"Plural mismatch, expected: {input_row['plural']}, got: {row.plural}"}

    # Normalize category: lowercase/strip, split optional ", rare form" suffix
    category = row.category.lower().strip()
    base, sep, rest = category.partition(',')
    base = base.strip()
    suffix = rest.strip()
    if base not in categories:
        return row, {'error_code': 'INVALID_CATEGORY',
                     'error_msg': f"Invalid category: {row.category}"}
    if suffix:
        if suffix != 'rare form':
            return row, {'error_code': 'INVALID_CATEGORY',
                         'error_msg': f"Invalid category suffix: {row.category}"}
        category = f"{base}, rare form"
    else:
        category = base

    return row._replace(category=category), None
