from unidecode import unidecode
from pathlib import Path
import os, sys

_dir = _config_dir
if str(_dir) not in sys.path:
    sys.path.insert(0, str(_dir))

SLOW_QUERY_THRESHOLD = 0.35

mode = os.getenv('REQ_MODE')
if mode not in ('ONCE', 'DYNAMIC'):
    raise ValueError('REQ_MODE env var must be defined and one of ONCE DYNAMIC')

x_title = 'POS Assignment'
key_file = '/home/kevina/wordlist/keys/openrouter.txt'

# models_config['qwen3-235b-a22b']['batch_size'] = 50
#models_config['deepseek-v3.2']['batch_size'] = 50
for k,v in models_config.items():
    v['reasoning'] = "none"
models_config["gpt-oss-120b"]["reasoning"] = "low"


pos_map = {
    'noun': 'n',
    'n': 'n',
    'pronoun': 'pn',
    'pron': 'pn',
    'verb': 'v',
    'v': 'v',
    'adj': 'aj',
    'adjective': 'aj',
    'adv': 'av', 
    'adverb': 'av', 
    'conj': 'c', 
    'conjunction': 'c', 
    'prep': 'pp', 
    'preposition': 'pp',
    'det': 'd', 
    'determiner': 'd',
    'interj': 'i', 
    'interjection': 'i', 
    'abbr': 'abbr',
    'abbreviation': 'abbr',
    'word-part': 'wp',
    'word_part': 'wp',
    'word part': 'wp',
}
orig_poses = {'?', 'n', 'v', 'm', 'a'}
possible_poses = {*pos_map.keys(), *orig_poses}

pos_classes = {'person','surname','place','name','demonym', 'abbr', 'none'}

pre_run = ['python3', str(_dir / 'combine.py')]
post_run = ['python3', str(_dir / 'combine.py')]

ENABLE_REDO = True if mode == 'ONCE' else False

if mode == 'ONCE':
    input_rows_sql = 'select * from input'
    def input_rows(conn, model):
        return conn.execute(input_rows_sql)
else:  # DYNAMIC
    DYNAMIC_MODE = True
    CROSS_MODEL_DEPS = True

    _candidates_sql = (_dir / "candidates-dynamic.sql.in").read_text()

    def create_candidates_temp_table(conn, model, run_id):
        conn.execute(_candidates_sql, {'model': model})

    def on_request_complete():
        from combine import update_uid, update_view, delete_from
        with open_db('w', 'update') as conn:
            if conn.execute("select 1 from completed_reqs").fetchone() is None:
                return
            conn.execute("analyze completed_reqs")
            filter_clause = "uid IN (SELECT uid FROM completed_reqs)"
            for row in conn.execute('SELECT * FROM input WHERE ' + filter_clause):
                update_uid(conn, row['uid'], row)
            update_view(conn, 'pos_class_cnts_by_model', filter_clause)
            update_view(conn, 'pos_class_cnts', filter_clause)
            delete_from(conn, 'pos_cnts_by_model', filter_clause)
            delete_from(conn, 'class_cnts_by_model', filter_clause)
            delete_from(conn, 'lemma_cnts_by_model', filter_clause)
            delete_from(conn, 'pos_cnts', filter_clause)
            delete_from(conn, 'class_cnts', filter_clause)
            delete_from(conn, 'lemma_cnts', filter_clause)
            conn.execute('DELETE FROM completed_reqs')

    def input_rows(conn, model):
        return conn.execute('SELECT * FROM input')

def validate_row(row, input_row):
    # Try and fix malformed rows
    new_row = None
    len_row = len(row)
    assert(row._expected == 6)
    len_diff = len_row - 6
    if len_diff == -1 and row[2] in pos_map:
        # skipped lemma field
        new_row = row._make((*row[:2], row[1], *row[2:]))
    elif len_diff == 1 and row[2] in orig_poses:
        # orig pos returned after word
        new_row = row._make((*row[:2], *row[3:]))
    elif len_diff == 1 and row[3] not in pos_map:
        # Look for duplicate cols starting from the end and eliminate dup.
        # Needs to be from the end as it is expected that lemma and word will
        # be the same and should only be eliminated as a last resort
        for i in range(len_row - 1, 0, -1):
            if row[i] == row[i-1]:
                new_row = row._make((*row[:i], *row[i+1:]))
                break
    elif len_diff < 0:
        new_row = row._make((*row, *(('',)*-len_diff)))
    if new_row:
        new_row, err = validate_row(new_row, input_row)
        if err is None:
            return new_row, err
    if len_diff != 0:
        # can't fix row, just return
        return row, None

    # Lemma matching (unidecode overlap check)
    input_word = unidecode(input_row['word']).lower()
    word = unidecode(row.word).lower()
    if input_word != word:
        return row, {'error_code': 'LEMMA_MISMATCH', 'error_msg': f"Lemma mismatch, expected: {input_row['word']}"}

    # POS normalization
    pos_str = row.pos.lower()
    pos = pos_map.get(row.pos, None)
    if pos is None and pos_str == '?':
        pos = ''

    pos_class = row.pos_class.lower()
    if pos_class == '':
        pos_class = 'none'

    if (pos_str in ('name','person','surname') and pos_class in ('name','person','surname')
        or pos_str == 'place' and pos_class == 'place'):
        pos = 'n'

    if pos is None:
        return row, {'error_code': 'INVALID_POS', 'error_msg': f"Invalid POS: {pos_str}"}

    if pos_class not in pos_classes:
        if pos == '':
            pos_class = 'none'
        else:
            return row, {'error_code': 'INVALID_POS_CLASS', 'error_msg': f"Invalid POS Class: {row.pos_class}"}
    if pos_class == 'none':
        pos_class = '';

    return row._replace(pos=pos,pos_class=pos_class), None

