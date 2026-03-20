from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional, Tuple

from size_decider import determine_final_size, model_size_score

def _borderline_other(size: int, borderline: Optional[str]) -> Optional[int]:
    # borderline is one of: '', '60/70', '70/80', '80/99'
    if borderline == '':
        return None
    a_str, b_str = borderline.split("/", 1)
    a = int(a_str)
    b = int(b_str)
    if size == a:
        return b
    if size == b:
        return a
    return None
    #raise ValueError(f"borderline {borderline!r} does not include size={size}")

def populate_size_scores(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.executescript(
                """
                drop table if exists model_size_scores;
                create table model_size_scores (
                  uid integer not null,
                  pos text not null,
                  model text not null,
                  size integer not null,
                  lower real not null,
                  higher real not null,
                  s_60 real not null,
                  s_70 real not null,
                  s_80 real not null,
                  s_99 real not null,
                  primary key (uid, pos, model)
                ) without rowid;

                drop table if exists final_size_scores;
                create table final_size_scores (
                  uid integer not null,
                  pos text not null,
                  size integer not null,
                  reason text not null,
                  excl text not null,
                  veto_60 boolean not null,
                  score_60 float not null,
                  score_70 float not null,
                  primary key (uid, pos)
                ) without rowid;
                """
            )

            per_uid: DefaultDict[Tuple[int, str], DefaultDict[str, List[Tuple[int, int, Optional[int]]]]] = defaultdict(
                lambda: defaultdict(list)
            )

            rows = conn.execute(
                """
                SELECT uid, pos, model, size, borderline, count(*) AS cnt
                FROM results_w_model
                GROUP BY uid, pos, model, size, borderline
                """
            )

            for row in rows:
                uid = row["uid"]
                pos = row["pos"]
                model = row["model"]
                size = row["size"]
                borderline_other = _borderline_other(size, row["borderline"])
                cnt = row["cnt"]

                per_uid[(uid, pos)][model].append((cnt, size, borderline_other))

            for (uid, pos), data in per_uid.items():
                outputs: Dict[str, Tuple[int, float]] = {
                    model: model_size_score(raw_outputs) for model, raw_outputs in data.items()
                }

                conn.executemany(
                    """
                    INSERT INTO model_size_scores (uid, pos, model, size, lower, higher, s_60, s_70, s_80, s_99)
                                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ((uid, pos, model, sz, float(lower), float(higher), *(float(m) for m in mass))
                     for model, (sz, lower, higher, mass) in outputs.items()))

                sz, reason = determine_final_size(outputs)
                conn.execute(
                    """
                    INSERT INTO final_size_scores (uid, pos, size, reason, excl, veto_60, score_60, score_70)
                                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uid, pos, sz, str(reason), reason.excl, reason.veto_60, float(reason.score_60), float(reason.score_70)))
    finally:
        conn.close()

if __name__ == '__main__':
    populate_size_scores('data.db');
