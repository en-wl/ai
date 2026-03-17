from unidecode import unidecode

x_title = 'Corpus Size Scoring'
post_run = ['python3', 'populate_size_scores.py']

def validate_row(row, input_row):
    # Lemma matching
    normalized = set(unidecode(l.strip().lower()) for l in row['lemmas'].split(','))
    expected = set(unidecode(l.strip().lower()) for l in input_row['lemmas'].split(','))
    if normalized.isdisjoint(expected):
        return row, {'error_code': 'LEMMA_MISMATCH', 'error_msg': f'Lemma mismatch: {normalized}'}

    # Size transformation ("excluded" -> 99)
    size_str = str(row['size']).lower() if not isinstance(row['size'], int) else None
    if size_str and size_str in ('excluded', 'exclude'):
        row['size'] = 99

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
