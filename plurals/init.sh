#!/bin/sh

set -e

if [ -e data.db ]; then
    echo "data.db exists"
    exit 1
fi

SQLITE="sqlite3 -batch -init ../misc/sqliterc.sql"

$SQLITE data.db ".read ../req/schema.sql"
$SQLITE data.db ".read schema-local.sql"
$SQLITE data.db ".read ../req/post.sql"

# Build the `input` table from two sources, with the dedup source-based (no
# uid-range assumptions):
#   - input.tsv      : real data, authoritative (uids 100+).  NOT in git; if it
#                      is absent only the calibration examples are loaded.
#   - test-input.sql : calibration examples (embedded instruction-following
#                      check), loaded via a temp `calibration` table.
# Real data wins on duplicate (noun,plural); calibration only fills the gaps, so
# a pair is never sent to the model twice (which would also mix an example into
# the default random sampling).  Everything is rebuilt from scratch each init.

if [ -f input.tsv ]; then
    $SQLITE data.db <<'EOF'
.mode tabs
.import --skip 1 input.tsv input
EOF
else
    echo "WARNING: input.tsv not found -- loading calibration examples only." >&2
fi

$SQLITE data.db <<'EOF'
create temp table calibration (
  uid integer primary key,
  noun text not null,
  plural text not null
);
.read test-input.sql
insert into input (uid, noun, plural)
  select uid, noun, plural
    from calibration c
   where not exists (select 1 from input i
                      where i.noun = c.noun and i.plural = c.plural);
EOF
