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

# Populate `input` (and the `sample` reference table) from all data sources.
# Kept in a separate, idempotent script so data can be (re-)added without a full
# rebuild; see populate.sh for the per-source keying and dedup rules.
./populate.sh
