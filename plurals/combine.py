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
  category_top_by_model(uid, model, category, cnt, total)
      Each model's own top category per uid (by vote count, rare_form folded in).
  category_top(uid, category, score)
      Combined top category per uid = argmax of the weighted score.
  rare_by_model(uid, model, rare_cnt, total, frac)
      Per-(uid, model) rare-form tally, independent of category: how many of the
      model's votes carried ", rare form" and what fraction of its total.
  rare_wavg(uid, score)
      Combined rare-form score = weighted average of the per-model fractions
      (MODEL_WEIGHTS), mirroring category_wavg.
  category_dist_model(uid, model, total_votes, <category columns>)
      Per-(uid, model) category distribution.
  category_dist(uid, <category columns>)
      Combined per-uid distribution = pivot of category_wavg.
  category_dist_cum(uid, <category, category_cnt columns>)
      Combined per-uid cumulative distribution, with a <category>_cnt column
      after each category giving the count of weighted models unanimous through
      that category (their cumulative fraction has reached 1.0).

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

CATEGORIES = ['natural', 'specialized', 'contrived', 'gerund', 'ungrammatical', 'invalid']

# Derived objects this script owns; dropped (as table OR view) before rebuild so
# a table<->view change is handled cleanly.  Includes legacy names no longer
# produced.
DERIVED = [
    'category_cnts_by_model', 'category_wavg',
    'category_top_by_model', 'category_top',
    'rare_by_model', 'rare_wavg',
    'category_dist_by_model', 'category_dist',
    'category_dist_cum', 'category_dist_cum_by_model',
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


def _cum_cols():
    # each category column = running sum of itself and all prior columns,
    # referencing the already-pivoted source view's columns
    return ',\n       '.join(
        f"round({' + '.join(CATEGORIES[:i+1])}, 4) as {c}"
        for i, c in enumerate(CATEGORIES))


def _unam_cnt_cols():
    # per category: how many models are unanimous through this category, i.e.
    # their cumulative fraction has reached 1.0
    return ',\n       '.join(
        f"sum(case when {c} >= 1.0 then 1 else 0 end) as {c}_cnt"
        for c in CATEGORIES)


def _cum_with_cnt_cols():
    # cumulative score column immediately followed by its unanimous-model count
    parts = []
    for i, c in enumerate(CATEGORIES):
        parts.append(f"round({' + '.join(CATEGORIES[:i+1])}, 4) as {c}")
        parts.append(f"{c}_cnt")
    return ',\n       '.join(parts)


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
    # Top category per (uid, model), with rare_form folded into the vote count
    # so the ranking is over categories, not (category, rare_form) combos.
    conn.execute("""
        create view category_top_by_model as
        select uid, model, category, cnt, total
          from (
            select uid, model, category, sum(cnt) as cnt, total,
                   row_number() over (
                     partition by uid, model order by sum(cnt) desc, category
                   ) as rn
              from category_cnts_by_model
             group by uid, model, category, total
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

    # rare-form tally, independent of category: per (uid, model), how many of the
    # model's votes carried ", rare form" and the fraction of its total.
    conn.execute("""
        create view rare_by_model as
        select uid, model,
               sum(case when rare_form = 1 then cnt else 0 end) as rare_cnt,
               total,
               round(1.0 * sum(case when rare_form = 1 then cnt else 0 end) / total, 4) as frac
          from category_cnts_by_model
         group by uid, model, total
    """)

    # combined rare-form score = weighted average of the per-model fractions,
    # normalized by the weight of the weighted models actually present for the
    # uid (same wsum logic as category_wavg, so it stays a proper average).
    # Materialized (like category_wavg) because the join to _weights, a temp
    # table, only resolves during this build.
    conn.execute("""
        create table rare_wavg (
          uid integer primary key,
          score real not null
        )
    """)
    conn.execute("""
        insert into rare_wavg (uid, score)
        with uid_wsum as (
          select uid, sum(weight) as wsum
            from (select distinct uid, model from category_cnts_by_model)
            join _weights using (model)
           group by uid)
        select r.uid,
               round(sum(w.weight * r.frac) / max(u.wsum), 6) as score
          from rare_by_model r
          join _weights w using (model)
          join uid_wsum u using (uid)
         group by r.uid
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

    conn.execute(f"""
        create view category_dist_cum_by_model as
        select uid, model, total_votes,
               {_cum_cols()}
          from category_dist_by_model
    """)

    # references category_dist_cum_by_model above, so must be created after it
    weighted_in = ', '.join(f"'{m}'" for m, _ in MODEL_WEIGHTS)
    conn.execute(f"""
        create view category_dist_cum as
        select category_dist.uid,
               {_cum_with_cnt_cols()}
          from category_dist
          join (
            select uid, {_unam_cnt_cols()}
              from category_dist_cum_by_model
             where model in ({weighted_in})
             group by uid
          ) using (uid)
    """)

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()
