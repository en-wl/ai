#!/usr/bin/env python3

import sqlite3
from collections import defaultdict

NAME_SUBTYPES = {'person', 'surname', 'place', 'demonym'}


def should_filter(input_row, output_row):
    input_pos = input_row['pos']
    output_pos = output_row['pos']
    """Filter out empty pos and Wrong!-but-consistent results."""
    if output_pos == '':
        return True
    if 'Wrong!' in (output_row['notes'] or ''):
        if input_pos == output_pos:
            return True
        if input_pos == 'm' and output_pos == 'v':
            return True
        if input_pos == 'a' and output_pos in ('aj', 'av'):
            return True
    return False


def apply_normalization(keys, count, fold):
    """Apply normalization rules.
    keys() -> iterable of current (pos, pos_class) keys
    count(key) -> numeric count for threshold checks
    fold(src, dst) -> merge src into dst
    """
    # abbr/abbr -> abbr/'': pos_class is redundant when pos is already abbr
    if ('abbr', 'abbr') in keys():
        fold(('abbr', 'abbr'), ('abbr', ''))

    # abbr POS folding: pos='abbr' -> unique POS with pos_class=('abbr','')
    abbr_keys = [k for k in keys() if k[0] == 'abbr']
    if abbr_keys:
        candidates = [k for k in keys() if k[0] != 'abbr' and k[1] == 'abbr']
        if len(candidates) == 1:
            for key in abbr_keys:
                fold(key, candidates[0])
        elif len(candidates) == 0:
            candidates = [k for k in keys() if k[0] != 'abbr' and k[1] == '']
            if len(candidates) == 1:
                dst = (candidates[0][0], 'abbr')
                fold(candidates[0], dst)
                for key in abbr_keys:
                    fold(key, dst)

    # abbr pos_class -> name pos_class (if name count >= 1.5)
    for pos in set(k[0] for k in keys() if k[1] == 'abbr'):
        if count((pos, 'name')) >= 1.5:
            fold((pos, 'abbr'), (pos, 'name'))

    # person/surname majority: tie -> surname (before name folding so it creates a unique candidate)
    cur = set(keys())
    person_poses = set(k[0] for k in cur if k[1] == 'person')
    surname_poses = set(k[0] for k in cur if k[1] == 'surname')
    for pos in person_poses & surname_poses:
        if count((pos, 'person')) > count((pos, 'surname')):
            fold((pos, 'surname'), (pos, 'person'))
        else:
            fold((pos, 'person'), (pos, 'surname'))

    # name folding: pos_class='name' -> unique specific subtype for that pos
    for pos in set(k[0] for k in keys() if k[1] == 'name'):
        specifics = [k for k in keys() if k[0] == pos and k[1] in NAME_SUBTYPES]
        if len(specifics) == 1 and (pos, 'name') in keys():
            fold((pos, 'name'), specifics[0])

    # empty pos_class -> unique non-empty pos_class (if non-empty count >= 1.5)
    for pos in set(k[0] for k in keys() if k[1] == ''):
        non_empty = [k for k in keys() if k[0] == pos and k[1] != '']
        if len(non_empty) == 1 and count(non_empty[0]) >= 1.5:
            fold((pos, ''), non_empty[0])


def update_model_data(conn, uid, model, input_row, results_rows):
    total = len(set(r['req_id'] for r in results_rows))

    req_id_sets = defaultdict(set)  # (pos, pos_class) -> set of req_ids
    skipped_req_ids = set()
    lemma_counts = defaultdict(lambda: defaultdict(int))  # key -> {lemma: count}

    for r in results_rows:
        if should_filter(input_row, r):
            skipped_req_ids.add(r['req_id'])
            continue
        key = (r['pos'], r['pos_class'])
        req_id_sets[key].add(r['req_id'])
        lemma_counts[key][r['lemma']] += 1

    if req_id_sets:
        def fold(src, dst):
            if src in req_id_sets:
                req_id_sets[dst] |= req_id_sets.pop(src)
            if src in lemma_counts:
                src_counts = lemma_counts.pop(src)
                for lemma, cnt in src_counts.items():
                    lemma_counts[dst][lemma] += cnt

        apply_normalization(
            keys=lambda: req_id_sets.keys(),
            count=lambda k: len(req_id_sets.get(k, set())),
            fold=fold,
        )

        for (pos, pos_class), req_ids in req_id_sets.items():
            lc = lemma_counts.get((pos, pos_class), {})
            best_lemma = max(lc, key=lc.get) if lc else None
            conn.execute(
                "insert into combined_w_model values (?,?,?,?,?,?,?)",
                (uid, model, len(req_ids), total, best_lemma, pos, pos_class))

    if skipped_req_ids:
        conn.execute(
            "insert into combined_w_model values (?,?,?,?,?,?,?)",
            (uid, model, len(skipped_req_ids), total, None, None, None))


def update_combined_data(conn, uid, input_row, combined_w_model_rows):
    valid = [r for r in combined_w_model_rows if r['pos'] is not None]
    if not valid:
        return

    by_model = defaultdict(dict)  # model -> {(pos, pos_class): cnt}
    model_totals = {}
    lemma_counts = defaultdict(lambda: defaultdict(int))  # key -> {lemma: count}

    for r in valid:
        m = r['model']
        key = (r['pos'], r['pos_class'])
        by_model[m][key] = by_model[m].get(key, 0) + r['cnt']
        model_totals[m] = r['total']
        if r['lemma']:
            lemma_counts[key][r['lemma']] += r['cnt']

    total_models = len(by_model)

    def global_keys():
        keys = set()
        for counts in by_model.values():
            keys.update(counts.keys())
        return keys

    def global_cnt_w(key):
        return sum(counts.get(key, 0) / model_totals[m]
                   for m, counts in by_model.items())

    def fold(src, dst):
        for counts in by_model.values():
            if src in counts:
                counts[dst] = counts.get(dst, 0) + counts.pop(src)
        if src in lemma_counts:
            src_counts = lemma_counts.pop(src)
            for lemma, cnt in src_counts.items():
                lemma_counts[dst][lemma] += cnt

    apply_normalization(global_keys, global_cnt_w, fold)

    # Aggregate across models
    for pos, pos_class in sorted(global_keys()):
        cnt = 0
        cnt_w = 0.0
        for m in by_model:
            m_cnt = by_model[m].get((pos, pos_class), 0)
            m_total = model_totals[m]
            if m_cnt == m_total:
                cnt += 1
            cnt_w += m_cnt / m_total

        lc = lemma_counts.get((pos, pos_class), {})
        best_lemma = max(lc, key=lc.get) if lc else ''

        conn.execute(
            "insert into combined values (?,?,?,?,?,?,?)",
            (uid, cnt, round(cnt_w, 6), total_models, best_lemma, pos, pos_class))


def update_uid(conn, uid, input_row):
    rows = conn.execute(
        "select * from results_w_model where uid = ?", (uid,)
    ).fetchall()
    if not rows:
        return

    by_model = defaultdict(list)
    for r in rows:
        by_model[r['model']].append(r)

    for model, model_rows in by_model.items():
        update_model_data(conn, uid, model, input_row, model_rows)

    cwm_rows = conn.execute(
        "select * from combined_w_model where uid = ?", (uid,)
    ).fetchall()
    update_combined_data(conn, uid, input_row, cwm_rows)


def main():
    conn = sqlite3.connect('data.db')
    conn.row_factory = sqlite3.Row
    conn.execute("begin immediate")

    conn.execute("delete from completed_reqs")
    conn.execute("drop table if exists combined_w_model")
    conn.execute("""
        create table combined_w_model (
            uid integer not null,
            model text not null,
            cnt integer not null,
            total integer not null,
            lemma text,
            pos text,
            pos_class text
        )
    """)

    conn.execute("drop table if exists combined")
    conn.execute("""
        create table combined (
            uid integer not null,
            cnt integer not null,
            cnt_w real not null,
            total integer not null,
            lemma text,
            pos text,
            pos_class text
        )
    """)

    inputs = {}
    for r in conn.execute("select uid, word, pos from input"):
        inputs[r['uid']] = dict(r)

    for uid in sorted(inputs):
        update_uid(conn, uid, inputs[uid])

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
