from unidecode import unidecode

x_title = 'Corpus Size Scoring'
DYNAMIC_MODE = True

def create_candidates_temp_table(conn, model, run_id):
    conn.execute('CREATE TEMP TABLE _candidates AS SELECT uid, num_runs AS reqs_cnt, 1 AS num FROM candidates WHERE model = :model',
                 {'model': model})

def on_request_complete():
    from size_decider import model_size_score
    from populate_size_scores import _borderline_other
    from collections import defaultdict

    with open_db('w') as conn:
        completed = conn.execute('SELECT DISTINCT uid, model FROM completed_reqs').fetchall()
        if not completed:
            return

        for r in completed:
            uid, model = r['uid'], r['model']

            rows = conn.execute('''
                SELECT pos, size, borderline, count(*) AS cnt
                FROM results_w_model
                WHERE uid = ? AND model = ?
                GROUP BY pos, size, borderline
            ''', (uid, model))

            per_pos = defaultdict(list)
            for row in rows:
                borderline_other = _borderline_other(row['size'], row['borderline'])
                per_pos[row['pos']].append((row['cnt'], row['size'], borderline_other))

            conn.execute('DELETE FROM model_size_scores WHERE uid = ? AND model = ?', (uid, model))

            for pos, raw_outputs in per_pos.items():
                sz, lower, higher, mass = model_size_score(raw_outputs)
                conn.execute('''
                    INSERT INTO model_size_scores (uid, pos, model, size, lower, higher, s_60, s_70, s_80, s_99)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (uid, pos, model, sz, float(lower), float(higher), *(float(m) for m in mass)))

        conn.execute('DELETE FROM completed_reqs')

def input_rows(conn, model):
    return conn.execute('SELECT * FROM input')

def validate_row(row, input_row):
    # Lemma matching
    normalized = set(unidecode(l.strip().lower()) for l in row.lemmas.split(','))
    expected = set(unidecode(l.strip().lower()) for l in input_row['lemmas'].split(','))
    if normalized.isdisjoint(expected):
        return row, {'error_code': 'LEMMA_MISMATCH', 'error_msg': f'Lemma mismatch: {normalized}'}

    # Parse and check size
    size_str = row.size.lower()
    if size_str in ('excluded', 'exclude'):
        size = 99
    else:
        try:
            size = int(size_str)
        except ValueError:
            size = None
    if size not in (60, 70, 80, 99):
        return row, {'error_code': "INVALID_SIZE", 'error_msg': f"Invalid size str: {size_str}"}

    # Borderline normalization
    bl = row.borderline.lower()
    if bl in ('', 'no'):
        borderline = ''
    elif bl in ('60/70', '70/80'):
        borderline = bl
    elif bl == 'incl/excl':
        borderline = '80/99' if size == 80 else ''
    else:
        return row, {'error_code': 'INVALID_BORDERLINE', 'error_msg': f'Invalid borderline: {bl}'}

    return row._replace(size=size, borderline=borderline), None
