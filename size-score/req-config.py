from unidecode import unidecode

x_title = 'Corpus Size Scoring'
post_run = ['python3', 'populate_size_scores.py']

# models_config['qwen3-235b-a22b']['batch_size'] = 50
models_config['deepseek-v3.2']['batch_size'] = 50

def validate_row(row, input_row):
    # POS normalization
    pos = row.pos.strip().lower()

    # Lemma matching (unidecode overlap check)
    input_word = unidecode(input_row['word']).strip().lower()
    words = set(unidecode(w).strip().lower() for w in row.words.split(','))
    if input_word not in words:
        return row, {'error_code': 'LEMMA_MISMATCH', 'error_msg': f"Lemma mismatch, expected: {input_row['word']}"}

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
        return row, {'error_code': 'INVALID_SIZE', 'error_msg': f"Invalid size str: {size_str}"}

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

    return row._replace(pos=pos, size=size, borderline=borderline), None
