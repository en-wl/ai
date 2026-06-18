#!/bin/sh

# Populate the `input` table (and the `sample` reference table) from all data
# sources.  Idempotent and additive: `input` is never cleared, so this can be
# re-run to fold in new/updated sources without rebuilding the DB.  init.sh
# calls this after creating the schema; it can also be run standalone against an
# existing data.db.
#
# Sources are loaded in order so the first to claim a (noun,plural) keeps it:
#   1. input.tsv      : real data, authoritative, carries its own uids (100+).
#                       NOT in git; if absent only the other sources load.
#                       Keyed by uid: a row whose uid already maps to a
#                       *different* (noun,plural) is a conflict -> skipped with a
#                       warning.  Same-uid/same-pair re-imports are no-ops.
#   2. test-input.sql : calibration examples (uid-less; keyed by noun,plural).
#   3. sample-input.tsv: ESDB reference data (uid-less; keyed by noun,plural).
#                        Also retained verbatim in the `sample` table (with its
#                        ESDB `category`) for later model-vs-ESDB alignment.
# The uid-less sources auto-assign uids and silently skip pairs already present.
# uid blocks: calibration 1-19, sample 20-99, input.tsv 100+.

set -e

if [ ! -e data.db ]; then
    echo "data.db not found -- run init.sh first" >&2
    exit 1
fi

SQLITE="sqlite3 -batch -init ../misc/sqliterc.sql"

# --- 1. input.tsv (uid-keyed; warn + skip on uid/(noun,plural) conflicts) ---
if [ -f input.tsv ]; then
    $SQLITE data.db <<'EOF'
create temp table _in (uid integer, noun text, plural text);
.mode tabs
.import --skip 1 input.tsv _in
.mode list
select 'WARNING: input.tsv uid ' || n.uid || ' conflicts with existing ('
       || i.noun || ',' || i.plural || '); skipping (' || n.noun || ',' || n.plural || ')'
  from _in n join input i on i.uid = n.uid
 where i.noun <> n.noun or i.plural <> n.plural;
-- OR IGNORE skips rows whose uid already exists (idempotent re-imports and the
-- conflicts warned above); brand-new uids insert.
insert or ignore into input (uid, noun, plural) select uid, noun, plural from _in;
EOF
else
    echo "WARNING: input.tsv not found -- skipping real data." >&2
fi

# --- 2. calibration (uid-less; auto-assign in 1-19, silently dedup) ---
$SQLITE data.db <<'EOF'
create temp table calibration (noun text not null, plural text not null);
.read test-input.sql
insert into input (uid, noun, plural)
select (select coalesce(max(uid), 0) from input where uid between 1 and 19)
       + row_number() over (order by noun, plural),
       noun, plural
  from calibration c
 where not exists (select 1 from input i where i.noun = c.noun and i.plural = c.plural);
EOF

# --- 3. sample (load into `sample` table, then auto-assign in 20-99) ---
$SQLITE data.db <<'EOF'
create temp table _samp (noun text, plural text, category text);
.mode tabs
.import --skip 1 sample-input.tsv _samp
insert or ignore into sample (noun, plural, category) select noun, plural, category from _samp;
insert into input (uid, noun, plural)
select (select coalesce(max(uid), 19) from input where uid between 20 and 99)
       + row_number() over (order by noun, plural),
       noun, plural
  from sample s
 where not exists (select 1 from input i where i.noun = s.noun and i.plural = s.plural);
EOF
