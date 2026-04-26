#!/usr/bin/env python3

import sqlite3
from collections import defaultdict
from pathlib import Path

NAME_SUBTYPES = {'person', 'surname', 'place', 'demonym'}

FINAL_MODELS = None
_config_path = Path('combine-config.py')
if _config_path.exists():
    exec(_config_path.read_text(), globals())

def pos_class_cnts_by_model_query(filter_clause=None):
    filter_clause = 'true' if filter_clause is None else f"({filter_clause})"

    return f"""with
  totals as (
    select uid, model, count(distinct req_id) as total
      from adj_results_by_model
     where {filter_clause}
     group by uid, model
  ),
  bucket_counts as (
    select uid, model, pos, pos_class, count(distinct req_id) as cnt,
           1.0 * count(distinct case when obscure then req_id end) / count(distinct req_id) as obscure
      from adj_results_by_model
     where pos is not null and {filter_clause}
     group by uid, model, pos, pos_class
  )
select b.uid, b.model, b.pos, b.pos_class, b.cnt, b.obscure, t.total
  from bucket_counts as b
  join totals as t using (uid, model)"""


def pos_cnts_by_model_query(filter_clause=None):
    filter_clause = 'true' if filter_clause is None else f"({filter_clause})"

    return f"""with
  totals as (
    select uid, model, count(distinct req_id) as total
      from adj_results_by_model
     where {filter_clause}
     group by uid, model
  ),
  pos_counts as (
    select uid, model, pos, count(distinct req_id) as cnt,
           1.0 * count(distinct case when obscure then req_id end) / count(distinct req_id) as obscure
      from adj_results_by_model
     where pos is not null and {filter_clause}
     group by uid, model, pos
  )
select p.uid, p.model, p.pos, p.cnt, p.obscure, t.total
  from pos_counts as p
  join totals as t using (uid, model)"""


def class_cnts_by_model_query(filter_clause=None):
    filter_clause = 'true' if filter_clause is None else f"({filter_clause})"

    return f"""with
  totals as (
    select uid, model, count(distinct req_id) as total
      from adj_results_by_model
     where {filter_clause}
     group by uid, model
  ),
  class_counts as (
    select uid, model, pos_class, count(distinct req_id) as cnt,
           1.0 * count(distinct case when obscure then req_id end) / count(distinct req_id) as obscure
      from adj_results_by_model
     where pos is not null and {filter_clause}
     group by uid, model, pos_class
  )
select c.uid, c.model, c.pos_class, c.cnt, c.obscure, t.total
  from class_counts as c
  join totals as t using (uid, model)"""


def lemma_cnts_by_model_query(filter_clause=None):
    filter_clause = 'true' if filter_clause is None else f"({filter_clause})"

    return f"""with
  bucket_counts as (
    select uid, model, pos, pos_class, count(distinct req_id) as total
      from adj_results_by_model
     where pos is not null and {filter_clause}
     group by uid, model, pos, pos_class
  ),
  lemma_counts as (
    select a.uid, a.model, a.pos, a.pos_class, r.lemma, count(distinct a.req_id) as cnt
      from (select * from adj_results_by_model where {filter_clause}) as a
      join results as r using (row_id)
     where a.pos is not null
     group by a.uid, a.model, a.pos, a.pos_class, r.lemma
  )
select l.uid, l.model, l.pos, l.pos_class, l.lemma, l.cnt, b.total
  from lemma_counts as l
  join bucket_counts as b using (uid, model, pos, pos_class)"""


def pos_class_cnts_query(filter_clause=None):
    filter_clause = 'true' if filter_clause is None else f"({filter_clause})"

    return f"""with
  model_totals as (
    select uid, model, count(distinct req_id) as total
      from adj_results
     where {filter_clause}
     group by uid, model
  ),
  bucket_model_counts as (
    select uid, model, pos, pos_class, count(distinct req_id) as cnt,
           1.0 * count(distinct case when obscure then req_id end) / count(distinct req_id) as obscure
      from adj_results
     where pos is not null and {filter_clause}
     group by uid, model, pos, pos_class
  ),
  exact_counts as (
    select b.uid,
           b.pos,
           b.pos_class,
           sum(case when b.cnt = t.total then 1 else 0 end) as cnt,
           round(sum(1.0 * b.cnt / t.total), 3) as cnt_w,
           round(avg(b.obscure), 4) as obscure
      from bucket_model_counts as b
      join model_totals as t using (uid, model)
     group by b.uid, b.pos, b.pos_class
  )
select e.uid, e.pos, e.pos_class, e.cnt, e.cnt_w, e.obscure, t.total
  from exact_counts as e
  join (
    select uid, count(*) as total
      from model_totals
     group by uid
  ) as t using (uid)"""


def pos_cnts_query(filter_clause=None):
    filter_clause = 'true' if filter_clause is None else f"({filter_clause})"

    return f"""with
  model_totals as (
    select uid, model, count(distinct req_id) as total
      from adj_results
     where {filter_clause}
     group by uid, model
  ),
  pos_model_counts as (
    select uid, model, pos, count(distinct req_id) as cnt,
           1.0 * count(distinct case when obscure then req_id end) / count(distinct req_id) as obscure
      from adj_results
     where pos is not null and {filter_clause}
     group by uid, model, pos
  ),
  pos_counts as (
    select p.uid,
           p.pos,
           sum(case when p.cnt = t.total then 1 else 0 end) as cnt,
           round(sum(1.0 * p.cnt / t.total), 3) as cnt_w,
           round(avg(p.obscure), 4) as obscure
      from pos_model_counts as p
      join model_totals as t using (uid, model)
     group by p.uid, p.pos
  )
select p.uid, p.pos, p.cnt, p.cnt_w, p.obscure, t.total
  from pos_counts as p
  join (
    select uid, count(*) as total
      from model_totals
     group by uid
  ) as t using (uid)"""


def class_cnts_query(filter_clause=None):
    filter_clause = 'true' if filter_clause is None else f"({filter_clause})"

    return f"""with
  model_totals as (
    select uid, model, count(distinct req_id) as total
      from adj_results
     where {filter_clause}
     group by uid, model
  ),
  class_model_counts as (
    select uid, model, pos_class, count(distinct req_id) as cnt,
           1.0 * count(distinct case when obscure then req_id end) / count(distinct req_id) as obscure
      from adj_results
     where pos is not null and {filter_clause}
     group by uid, model, pos_class
  ),
  class_counts as (
    select c.uid,
           c.pos_class,
           sum(case when c.cnt = t.total then 1 else 0 end) as cnt,
           round(sum(1.0 * c.cnt / t.total), 3) as cnt_w,
           round(avg(c.obscure), 4) as obscure
      from class_model_counts as c
      join model_totals as t using (uid, model)
     group by c.uid, c.pos_class
  )
select c.uid, c.pos_class, c.cnt, c.cnt_w, c.obscure, t.total
  from class_counts as c
  join (
    select uid, count(*) as total
      from model_totals
     group by uid
  ) as t using (uid)"""


def lemma_cnts_query(filter_clause=None):
    filter_clause = 'true' if filter_clause is None else f"({filter_clause})"

    return f"""with
  base as (
    select a.uid, a.model, a.req_id, a.pos, a.pos_class, r.lemma
      from (select * from adj_results where {filter_clause}) as a
      join results as r using (row_id)
     where a.pos is not null
  ),
  bucket_model_counts as (
    select uid, model, pos, pos_class, count(distinct req_id) as bucket_cnt
      from base
     group by uid, model, pos, pos_class
  ),
  bucket_totals as (
    select uid, pos, pos_class, count(distinct model) as total
      from bucket_model_counts
     group by uid, pos, pos_class
  ),
  lemma_model_counts as (
    select uid, model, pos, pos_class, lemma, count(distinct req_id) as lemma_cnt
      from base
     group by uid, model, pos, pos_class, lemma
  ),
  lemma_counts as (
    select l.uid,
           l.pos,
           l.pos_class,
           l.lemma,
           sum(case when l.lemma_cnt = b.bucket_cnt then 1 else 0 end) as cnt,
           round(sum(1.0 * l.lemma_cnt / b.bucket_cnt), 3) as cnt_w
      from lemma_model_counts as l
      join bucket_model_counts as b using (uid, model, pos, pos_class)
     group by l.uid, l.pos, l.pos_class, l.lemma
  )
select l.uid, l.pos, l.pos_class, l.lemma, l.cnt, l.cnt_w, b.total
  from lemma_counts as l
  join bucket_totals as b using (uid, pos, pos_class)"""


VIEWS = {
    'pos_class_cnts_by_model': pos_class_cnts_by_model_query,
    'pos_cnts_by_model': pos_cnts_by_model_query,
    'class_cnts_by_model': class_cnts_by_model_query,
    'lemma_cnts_by_model': lemma_cnts_by_model_query,
    'pos_class_cnts': pos_class_cnts_query,
    'pos_cnts': pos_cnts_query,
    'class_cnts': class_cnts_query,
    'lemma_cnts': lemma_cnts_query
}

def delete_from(conn, name, filter_clause = None):
    if filter_clause is None:
        conn.execute(f"delete from {name}")
    else:
        conn.execute(f"delete from {name} where ({filter_clause})")

def update_view(conn, name, filter_clause = None):
    delete_from(conn, name, filter_clause)
    conn.execute(f"insert into {name}\n"
                 f"{VIEWS[name](filter_clause)}")

def create_as_view(conn, name, filter_clause = None):
    view_name = f"{name}_view"
    conn.execute(f"drop view if exists {view_name}")
    conn.execute(f"create view {view_name} as\n"
                 f"{VIEWS[name](filter_clause)}")

#
#
#

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
            candidates = [k for k in data.keys() if k[0] not in ('abbr', 'wp') and k[1] == '']
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

    for r in results_rows:
        if should_filter(input_row, r):
            conn.execute(
                "insert into adj_results_by_model values (?,?,?,?,?,?,?)",
                (uid, model, r['req_id'], r['row_id'], None, None, None))
            continue

        data[(r['pos'], r['pos_class'])].add_row(r)

        if 'Fragment.' in (r['notes'] or ''):
            data[('wp', '' if r['pos_class'] == 'abbr' else r['pos_class'])].add_row(r)

    apply_normalization(data)

    for (pos, pos_class), d in data.items():
        conn.executemany(
            "insert into adj_results_by_model values (?,?,?,?,?,?,?)",
            ((uid, model, row['req_id'], row['row_id'], pos, pos_class,
              1 if 'Obscure!' in (row['notes'] or '') else 0)
             for row in d.rows))

def update_combined_data(conn, uid):
    filter_clause = 'true'
    if FINAL_MODELS is not None:
        filter_clause = "model in ({})".format(','.join(f"'{model}'" for model in FINAL_MODELS))
    rows = []
    for row in conn.execute(f"select * from adj_results_by_model where uid = ? and {filter_clause}", (uid,)):
        if row['pos'] is None:
            conn.execute(
                "insert into adj_results values (?,?,?,?,?,?,?)",
                (uid, row['model'], row['req_id'], row['row_id'], None, None, None))
        else:
            rows.append(row)
    if not rows:
        return

    model_totals = dict(conn.execute(
        """select model, count(distinct req_id)
             from adj_results_by_model
            where uid = ?
            group by model""",
        (uid,)).fetchall())

    class Data:
        __slots__ = ('req_ids_by_model', 'rows')

        def __init__(self):
            self.req_ids_by_model = defaultdict(set)
            self.rows = []

        def count(self):
            return sum(
                len(req_ids) / model_totals[model]
                for model, req_ids in self.req_ids_by_model.items()
            )

        def merge(self, other):
            for model, req_ids in other.req_ids_by_model.items():
                self.req_ids_by_model[model] |= req_ids
            self.rows += other.rows

        def add_row(self, r):
            self.req_ids_by_model[r['model']].add(r['req_id'])
            self.rows.append(r)

    data = defaultdict(Data)
    for r in rows:
        data[(r['pos'], r['pos_class'])].add_row(r)

    apply_normalization(data)

    for (pos, pos_class), d in data.items():
        conn.executemany(
            "insert into adj_results values (?,?,?,?,?,?,?)",
            ((uid, row['model'], row['req_id'], row['row_id'], pos, pos_class,
              row['obscure'])
             for row in d.rows))


def update_uid(conn, uid, input_row):
    conn.execute("delete from adj_results where uid = ?", (uid,))
    conn.execute("delete from adj_results_by_model where uid = ?", (uid,))

    by_model = defaultdict(list)
    for r in conn.execute(
            "select model, req_id, row_id, pos, pos_class, notes from results_w_model where uid = ?""",
            (uid,)):
        by_model[r['model']].append(r)

    for model, model_rows in by_model.items():
        update_model_data(conn, uid, model, input_row, model_rows)

    update_combined_data(conn, uid)


def main():
    _dir = Path(__file__).resolve().parent
    conn = sqlite3.connect('data.db')
    conn.row_factory = sqlite3.Row
    conn.executescript((_dir / 'combine-init.sql').read_text())

    conn.execute("delete from completed_reqs")

    inputs = {}
    for r in conn.execute("select uid, pos from input"):
        inputs[r['uid']] = r

    for uid in sorted(inputs):
        update_uid(conn, uid, inputs[uid])

    for name in VIEWS.keys():
        create_as_view(conn, name)
        update_view(conn, name)

    conn.execute("analyze")
    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
