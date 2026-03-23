from unidecode import unidecode

x_title = 'Corpus Size Scoring'
post_run = ['python3', 'populate_size_scores.py']

def validate_row(cells, input_row):
    ci = result_col_idx

    # Lemma matching
    normalized = set(unidecode(l.strip().lower()) for l in cells[ci['lemmas']].split(','))
    expected = set(unidecode(l.strip().lower()) for l in input_row['lemmas'].split(','))
    if normalized.isdisjoint(expected):
        return cells, {'error_code': 'LEMMA_MISMATCH', 'error_msg': f'Lemma mismatch: {normalized}'}

    # Parse and check size
    size_str = cells[ci['size']].lower()
    if size_str in ('excluded', 'exclude'):
        cells[ci['size']] = '99'
    else:
        try:
            int(size_str)
        except ValueError:
            return cells, {'error_code': "INVALID_SIZE", 'error_msg': f"Invalid size str: {size_str}"}
        if int(size_str) not in (60, 70, 80, 99):
            return cells, {'error_code': "INVALID_SIZE", 'error_msg': f"Invalid size str: {size_str}"}

    # Borderline normalization
    bl = cells[ci['borderline']].lower()
    if bl in ('', 'no'):
        cells[ci['borderline']] = ''
    elif bl in ('60/70', '70/80'):
        cells[ci['borderline']] = bl
    elif bl == 'incl/excl':
        cells[ci['borderline']] = '80/99' if int(cells[ci['size']]) == 80 else ''
    else:
        return cells, {'error_code': 'INVALID_BORDERLINE', 'error_msg': f'Invalid borderline: {bl}'}

    return cells, None
