#!/usr/bin/env python3
"""Combine step for the plurals task.

Folds the optional ", rare form" suffix into the base category (in one place,
the `_norm` temp table), tallies votes, and derives the analysis tables/views.

Materialized tables:
  category_cnts_by_model(uid, model, category, rare_form, cnt, total)
      Raw per-model tally; `total` is all votes for the uid by that model.
  category_wavg(uid, category, score)
      Combined per-uid category distribution as a weighted average of the
      per-model fractions (MODEL_WEIGHTS below).  This is the single place the
      weighted-average logic lives; the combined pivot and top views derive
      from it.  `score` sums to ~1 per uid.

Views:
  category_top_by_model(uid, model, category, rare_form, cnt, total)
      Each model's own top (category, rare_form) per uid (by vote count).
  category_top(uid, category, score)
      Combined top category per uid = argmax of the weighted score.
  category_dist_model(uid, model, total_votes, <category columns>)
      Per-(uid, model) category distribution.
  category_dist(uid, <category columns>)
      Combined per-uid distribution = pivot of category_wavg.

Run directly (`./combine.py`) or wire as pre_run/post_run in req-config.py.
Connects to data.db in the current directory; does not import req._config.
"""

import sqlite3

# `, rare form` is the normalized suffix validate_row attaches (see
# req-config.py); strip it off and record the base category only.
RARE_SUFFIX = ', rare form'

# Per-model weights for the combined (category_wavg) distribution.  Edit here to
# change the mix or add models.
MODEL_WEIGHTS = [
    ('gemma-4-31b',  1/4),
    ('gpt-5.4',      1/4),
    ('gpt-oss-120b', 1/4),
    ('qwen3.5-397b-a17b', 1/4)
]

CATEGORIES = ['natural', 'specialized', 'contrived', 'ungrammatical', 'gerund', 'invalid']

# Derived objects this script owns; dropped (as table OR view) before rebuild so
# a table<->view change is handled cleanly.  Includes legacy names no longer
# produced.
DERIVED = [
    'category_cnts_by_model', 'category_wavg',
    'category_top_by_model', 'category_top',
    'category_dist_by_model', 'category_dist',
    'category_dist_by_uid_model', 'category_dist_by_uid', 'category_cnts',  # legacy
]


def _wavg_pivot_cols():
    # one column per category: its weighted score (0 if the category got no votes)
    return ',\n       '.join(
        f"round(coalesce(sum(case when category = '{c}' then score end), 0), 4) as {c}"
        for c in CATEGORIES)


def _frac_cols():
    # one column per category: fraction of votes in the current group
    return ',\n       '.join(
        f"round(1.0 * sum(case when category = '{c}' then cnt else 0 end) / sum(cnt), 4) as {c}"
        for c in CATEGORIES)


def main():
    conn = sqlite3.connect('data.db')
    conn.row_factory = sqlite3.Row

    # Transient DYNAMIC-mode table (created by req/schema.sql); clear it so it
    # doesn't accumulate across runs.
    conn.execute('delete from completed_reqs')

    for name in DERIVED:
        row = conn.execute("select type from sqlite_master where name = ?", (name,)).fetchone()
        if row:
            conn.execute(f"drop {row['type']} if exists {name}")

    # --- base tally: the only place the ", rare form" fold happens ---
    conn.execute("""
        create temp table _norm as
        select uid, model,
               case when category like '%' || :suffix
                    then substr(category, 1, length(category) - length(:suffix))
                    else category end as category,
               case when category like '%' || :suffix then 1 else 0 end as rare_form
          from results_w_model
    """, {'suffix': RARE_SUFFIX})

    conn.execute("""
        create table category_cnts_by_model (
          uid integer not null,
          model text not null,
          category text not null,
          rare_form integer not null,
          cnt integer not null,
          total integer not null,
          primary key (uid, model, category, rare_form)
        )
    """)
    conn.execute("""
        insert into category_cnts_by_model (uid, model, category, rare_form, cnt, total)
        select uid, model, category, rare_form, count(*) as cnt,
               sum(count(*)) over (partition by uid, model) as total
          from _norm
         group by uid, model, category, rare_form
    """)

    # --- weighted combined distribution (single source of the weighted logic) ---
    conn.execute("create temp table _weights (model text primary key, weight real)")
    conn.executemany("insert into _weights values (?, ?)", MODEL_WEIGHTS)

    conn.execute("""
        create table category_wavg (
          uid integer not null,
          category text not null,
          score real not null,
          primary key (uid, category)
        )
    """)
    # score(uid, cat) = sum_m weight_m * frac_{m,cat} / sum_m weight_m, over the
    # weighted models present for the uid (so it stays a proper average and sums
    # to ~1 per uid).  frac is the model's own fraction for that (uid, category).
    conn.execute("""
        insert into category_wavg (uid, category, score)
        with
          frac as (
            select uid, model, category, 1.0 * sum(cnt) / total as frac
              from category_cnts_by_model
             group by uid, model, category, total),
          uid_wsum as (
            select uid, sum(weight) as wsum
              from (select distinct uid, model from category_cnts_by_model)
              join _weights using (model)
             group by uid)
        select f.uid, f.category,
               round(sum(w.weight * f.frac) / max(u.wsum), 6) as score
          from frac f
          join _weights w using (model)
          join uid_wsum u using (uid)
         group by f.uid, f.category
    """)

    # --- views ---
    conn.execute("""
        create view category_top_by_model as
        select uid, model, category, rare_form, cnt, total
          from (
            select uid, model, category, rare_form, cnt, total,
                   row_number() over (
                     partition by uid, model order by cnt desc, category, rare_form
                   ) as rn
              from category_cnts_by_model
          )
         where rn = 1
    """)

    conn.execute("""
        create view category_top as
        select uid, category, score
          from (
            select uid, category, score,
                   row_number() over (
                     partition by uid order by score desc, category
                   ) as rn
              from category_wavg
          )
         where rn = 1
    """)

    conn.execute(f"""
        create view category_dist_by_model as
        select uid, model, sum(cnt) as total_votes,
               {_frac_cols()}
          from category_cnts_by_model
         group by uid, model
    """)

    conn.execute(f"""
        create view category_dist as
        select uid,
               {_wavg_pivot_cols()}
          from category_wavg
         group by uid
    """)

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
