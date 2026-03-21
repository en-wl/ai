from unidecode import unidecode

x_title = 'Corpus Size Scoring'
post_run = ['python3', 'populate_size_scores.py']

# Canonical POS codes matching size-score-simple
_pos_map = {
    'n': 'n', 'noun': 'n',
    'v': 'v', 'verb': 'v',
    'aj': 'aj', 'adj': 'aj', 'adjective': 'aj',
    'av': 'av', 'adv': 'av', 'adverb': 'av',
    'pn': 'pn', 'pronoun': 'pn', 'pron': 'pn',
    'c': 'c', 'conj': 'c', 'conjunction': 'c',
    'pp': 'pp', 'prep': 'pp', 'preposition': 'pp',
    'd': 'd', 'det': 'd', 'determiner': 'd',
    'i': 'i', 'interj': 'i', 'interjection': 'i',
    'abbr': 'abbr', 'abbreviation': 'abbr',
}

# Uncertain POS codes — the LLM is expected to correct these
_uncertain_pos = {'?', 'n', 'm', 'a'}

def validate_row(row, input_row):
    # POS normalization
    raw_pos = row['pos'].strip().lower()
    canonical = _pos_map.get(raw_pos)
    if canonical is None:
        return row, {'error_code': 'INVALID_POS', 'error_msg': f'Unknown POS: {row["pos"]}'}
    row['pos'] = canonical

    # POS enforcement: if input POS is exact, output must match
    input_pos = input_row['pos'].strip().lower()
    if input_pos not in _uncertain_pos:
        input_canonical = _pos_map.get(input_pos)
        if input_canonical is not None and canonical != input_canonical:
            return row, {'error_code': 'POS_MISMATCH',
                         'error_msg': f'Input POS is {input_pos} but LLM returned {row["pos"]}'}

    # Lemma matching (unidecode overlap check)
    normalized = set(unidecode(l.strip().lower()) for l in row['lemmas'].split(','))
    expected = set(unidecode(l.strip().lower()) for l in input_row['lemmas'].split(','))
    if normalized.isdisjoint(expected):
        return row, {'error_code': 'LEMMA_MISMATCH', 'error_msg': f'Lemma mismatch: {normalized}'}

    # Parse and check size
    size_str = row['size'].lower()
    if size_str in ('excluded', 'exclude'):
        size = 99
    else:
        try:
            size = int(size_str)
        except ValueError:
            size = None
    if size not in (60, 70, 80, 99):
        return row, {'error_code': 'INVALID_SIZE', 'error_msg': f"Invalid size str: {size_str}"}
    row['size'] = size

    # Borderline normalization
    bl = row['borderline'].lower()
    if bl in ('', 'no'):
        row['borderline'] = ''
    elif bl in ('60/70', '70/80'):
        row['borderline'] = bl
    elif bl == 'incl/excl':
        row['borderline'] = '80/99' if row['size'] == 80 else ''
    else:
        return row, {'error_code': 'INVALID_BORDERLINE', 'error_msg': f'Invalid borderline: {bl}'}

    return row, None
