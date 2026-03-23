from unidecode import unidecode

x_title = 'Corpus Size Scoring'
post_run = ['python3', 'populate_size_scores.py']

# models_config['qwen3-235b-a22b']['batch_size'] = 50
models_config['deepseek-v3.2']['batch_size'] = 50

def validate_row(cells, input_row):
    ci = result_col_idx

    # POS normalization
    cells[ci['pos']] = cells[ci['pos']].strip().lower()

    # Lemma matching (unidecode overlap check)
    input_word = unidecode(input_row['word']).strip().lower()
    words = set(unidecode(w).strip().lower() for w in cells[ci['words']].split(','))
    if input_word not in words:
        return cells, {'error_code': 'LEMMA_MISMATCH', 'error_msg': f"Lemma mismatch, expected: {input_row['word']}"}

    # Parse and check size
    size_str = cells[ci['size']].lower()
    if size_str in ('excluded', 'exclude'):
        cells[ci['size']] = '99'
    else:
        try:
            int(size_str)
        except ValueError:
            return cells, {'error_code': 'INVALID_SIZE', 'error_msg': f"Invalid size str: {size_str}"}
        if int(size_str) not in (60, 70, 80, 99):
            return cells, {'error_code': 'INVALID_SIZE', 'error_msg': f"Invalid size str: {size_str}"}

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
