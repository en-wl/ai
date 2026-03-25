from unidecode import unidecode

x_title = 'Corpus Size Scoring'
post_run = ['python3', 'populate_size_scores.py']
key_file = '/home/kevina/wordlist/keys/openrouter.txt'

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
}
orig_poses = {'?', 'n', 'v', 'm', 'a'}
possible_poses = {*pos_map.keys(), *orig_poses}

# models_config['qwen3-235b-a22b']['batch_size'] = 50
models_config['deepseek-v3.2']['batch_size'] = 50

def validate_row(row, input_row):
    # Try and fix malformed rows
    if (len(row) > row._expected):
        WORDS_IDX = row._idx['words']
        POS_IDX = row._idx['pos']
        new_row = None
        if row[WORDS_IDX+1].lower() not in possible_poses:
            # The cell after WORDS_IDX isn't a POS, so it's likely a split word.
            # Merge with comma and skip the extra cell
            new_row = row._make(row[:WORDS_IDX] + (row[WORDS_IDX] + ', ' + row[WORDS_IDX+1],) + row[WORDS_IDX+2:])
        elif row[POS_IDX].lower() in orig_poses and row[POS_IDX + 1].lower() in possible_poses:
            # The model output an orig POS followed by a valid POS. Drop the orig one
            new_row = row._make(row[:POS_IDX] + row[POS_IDX+1:])
        elif row[POS_IDX+1].lower() in orig_poses and row[POS_IDX].lower() in possible_poses:
            # The valid POS is at POS_IDX, orig POS leaked into next column. Drop it
            new_row = row._make(row[:POS_IDX+1] + row[POS_IDX+2:])
        if new_row:
            new_row, err = validate_row(new_row, input_row)
            if err is None:
                return new_row, err
        # can't fix row, just return
        return row, None

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

    # POS normalization
    pos_str = row.pos.lower()
    pos = pos_map.get(pos_str, None)
    if pos is None and size == 99:
        pos = ''
    if pos is None and pos_str == input_row['pos']:
        pos = pos_str
    if pos == '?':
        pos = ''
    if pos is None:
        return row, {'error_code': 'INVALID_POS', 'error_msg': f"Invalid POS: {pos_str}"}

    # Lemma matching (unidecode overlap check)
    input_word = unidecode(input_row['word']).strip().lower()
    words = set(unidecode(w).strip().lower() for w in row.words.split(','))
    if input_word not in words:
        return row, {'error_code': 'LEMMA_MISMATCH', 'error_msg': f"Lemma mismatch, expected: {input_row['word']}"}

    # Borderline normalization
    bl = row.borderline.lower()
    if bl in ('', '-', '—', 'no'):
        borderline = ''
    elif bl in ('60/70', '70/80'):
        borderline = bl
    elif bl == 'incl/excl':
        borderline = '80/99' if size in (80,99) else ''
    elif bl == 'excl':
        borderline = '80/99' if size <= 80 else ''
    else:
        return row, {'error_code': 'INVALID_BORDERLINE', 'error_msg': f'Invalid borderline: {bl}'}

    return row._replace(pos=pos, size=size, borderline=borderline), None
