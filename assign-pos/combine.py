#!/usr/bin/env python3

import sqlite3
from collections import defaultdict

import time

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

def apply_normalization(data):
    """Apply normalization rules.
    data: defaultdict of (pos, pos_class) -> obj with count() and merge(other) methods
    """
    # abbr/abbr -> abbr/'': pos_class is redundant when pos is already abbr
    if ('abbr', 'abbr') in data:
        data[('abbr', '')].merge(data.pop(('abbr', 'abbr')))

    # abbr POS folding: pos='abbr' -> unique POS with pos_class='abbr' or ''
    abbr_keys = [k for k in data.keys() if k[0] == 'abbr']
    if abbr_keys:
        candidates = [k for k in data.keys() if k[0] not in ('abbr', 'wp') and k[1] == 'abbr']
        if len(candidates) == 1:
            for key in abbr_keys:
                data[candidates[0]].merge(data.pop(key))
        elif len(candidates) == 0:
            candidates = [k for k in data.keys() if k[0] not in ('abbr','wp') and k[1] == '']
            if len(candidates) == 1:
                dst = (candidates[0][0], 'abbr')
                data[dst].merge(data.pop(candidates[0]))
                for key in abbr_keys:
                    data[dst].merge(data.pop(key))

    # abbr pos_class -> name pos_class (if name count >= 1.5)
    for pos in set(k[0] for k in data.keys() if k[1] == 'abbr'):
        if (pos, 'name') in data and data[(pos, 'name')].count() >= 1.5:
            data[(pos, 'name')].merge(data.pop((pos, 'abbr')))

    # person/surname majority: tie -> surname
    person_poses = set(k[0] for k in data.keys() if k[1] == 'person')
    surname_poses = set(k[0] for k in data.keys() if k[1] == 'surname')
    for pos in person_poses & surname_poses:
        if data[(pos, 'person')].count() > data[(pos, 'surname')].count():
            data[(pos, 'person')].merge(data.pop((pos, 'surname')))
        else:
            data[(pos, 'surname')].merge(data.pop((pos, 'person')))

    # name folding: pos_class='name' -> unique specific subtype for that pos
    for pos in set(k[0] for k in data.keys() if k[1] == 'name'):
        specifics = [k for k in data.keys() if k[0] == pos and k[1] in NAME_SUBTYPES]
        if len(specifics) == 1:
            data[specifics[0]].merge(data.pop((pos, 'name')))

    # empty pos_class -> unique non-empty pos_class (if non-empty count >= 1.5)
    for pos in set(k[0] for k in data.keys() if k[1] == ''):
        non_empty = [k for k in data.keys() if k[0] == pos and k[1] != '']
        if len(non_empty) == 1 and data[non_empty[0]].count() >= 1.5:
            data[non_empty[0]].merge(data.pop((pos, '')))

def update_model_data(conn, uid, model, input_row, results_rows):
    total = len(set(r['req_id'] for r in results_rows))

    class Data:
        __slots__ = ('req_ids', 'rows')
        def __init__(self):
            self.req_ids = set()
            self.rows = []
        def count(self):
            return len(self.req_ids)
        def merge(self, other):
            self.req_ids |= other.req_ids
            self.rows += other.rows
        def add_row(self, r):
            self.req_ids.add(r['req_id'])
            self.rows.append(r)

    data = defaultdict(Data)  # (pos, pos_class) -> Data
    skipped_req_ids = set()

    for r in results_rows:
        if should_filter(input_row, r):
            skipped_req_ids.add(r['req_id'])
            continue

        data[(r['pos'], r['pos_class'])].add_row(r)

        if 'Fragment.' in (r['notes'] or ''):
            data[('wp', '' if r['pos_class'] == 'abbr' else r['pos_class'])].add_row(r)

    apply_normalization(data)

    by_pos = defaultdict(set)
    for (pos, _), d in data.items():
        by_pos[pos] |= d.req_ids

    for (pos, pos_class), d in data.items():
        lemma_counts = defaultdict(int)
        for row in d.rows:
            if row['lemma']:
                lemma_counts[row['lemma']] += 1
        best_lemma = max(lemma_counts, key=lemma_counts.get)
        conn.execute(
            "insert into combined_w_model values (?,?,?,?,?,?,?,?)",
            (uid, model, best_lemma, pos, pos_class, len(d.req_ids), len(by_pos[pos]), total))

    if skipped_req_ids:
        conn.execute(
            "insert into combined_w_model values (?,?,?,?,?,?,?,?)",
            (uid, model, None, None, None, len(skipped_req_ids), len(skipped_req_ids), total))

def update_combined_data(conn, uid, input_row, combined_w_model_rows):
    valid = [r for r in combined_w_model_rows if r['pos'] is not None]
    if not valid:
        return

    model_totals = {}
    for r in valid:
        model_totals[r['model']] = r['total']
    total_models = len(model_totals)

    class Data:
        __slots__ = ('model_counts', 'rows')
        def __init__(self):
            self.model_counts = {}   # model -> count
            self.rows = []
        def count(self):
            return sum(cnt / model_totals[m] for m, cnt in self.model_counts.items())
        def merge(self, other):
            for m, cnt in other.model_counts.items():
                self.model_counts[m] = self.model_counts.get(m, 0) + cnt
            self.rows += other.rows

    data = defaultdict(Data)
    for r in valid:
        key = (r['pos'], r['pos_class'])
        data[key].model_counts[r['model']] = data[key].model_counts.get(r['model'], 0) + r['cnt']
        data[key].rows.append(r)

    apply_normalization(data)

    # Build pos-level model counts from rows' pos_cnt (already deduplicated per-model)
    by_pos = defaultdict(lambda: defaultdict(int))  # current_pos -> {model: pos_cnt}
    seen = set()
    for (pos, _), d in data.items():
        for row in d.rows:
            key = (pos, row['model'], row['pos'])  # (current_pos, model, original_pos)
            if key not in seen:
                seen.add(key)
                by_pos[pos][row['model']] += row['pos_cnt']

    # Aggregate across models
    for pos, pos_class in sorted(data):
        d = data[(pos, pos_class)]
        cnt = 0
        cnt_w = 0.0
        pos_cnt = 0
        pos_cnt_w = 0.0
        for m, m_total in model_totals.items():
            m_cnt = d.model_counts.get(m, 0)
            m_pos_cnt = by_pos[pos].get(m, 0)
            if m_cnt == m_total:
                cnt += 1
            cnt_w += m_cnt / m_total
            if m_pos_cnt == m_total:
                pos_cnt += 1
            pos_cnt_w += m_pos_cnt / m_total

        lemma_counts = defaultdict(int)
        for row in d.rows:
            if row['lemma']:
                lemma_counts[row['lemma']] += row['cnt']
        best_lemma = max(lemma_counts, key=lemma_counts.get)

        conn.execute(
            "insert into combined values (?,?,?,?,?,?,?,?,?)",
            (uid, best_lemma, pos, pos_class, cnt, cnt_w, pos_cnt, pos_cnt_w, total_models))


def update_uid(conn, uid, input_row):
    rows = conn.execute("select * from results_w_model where uid = ?", (uid,)).fetchall()
    if not rows:
        return

    by_model = defaultdict(list)
    for r in rows:
        by_model[r['model']].append(r)

    for model, model_rows in by_model.items():
        update_model_data(conn, uid, model, input_row, model_rows)

    cwm_rows = conn.execute("select * from combined_w_model where uid = ?", (uid,)).fetchall()
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
            lemma text,
            pos text,
            pos_class text,
            cnt integer not null,
            pos_cnt integer not null,
            total integer not null
        )
    """)
    conn.execute("create index combined_w_model_idx on combined_w_model(uid, model)")

    conn.execute("drop table if exists combined")
    conn.execute("""
        create table combined (
            uid integer not null,
            lemma text,
            pos text,
            pos_class text,
            cnt integer not null,
            cnt_w real not null,
            pos_cnt integer not null,
            pos_cnt_w real not null,
            total integer not null
        )
    """)
    conn.execute("create index combined_idx on combined(uid)")

    inputs = {}
    for r in conn.execute("select uid, word, pos from input"):
        inputs[r['uid']] = dict(r)

    for uid in sorted(inputs):
        update_uid(conn, uid, inputs[uid])

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
