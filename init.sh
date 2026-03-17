#!/bin/sh

set -e

if [ -e data.db ]; then
    echo "data.db exists"
    exit 1
fi

SQLITE="sqlite3 -batch -init sqliterc.sql"

./system_prompt.sh > ./system_prompt.md

$SQLITE data.db ".read schema.sql"
$SQLITE data.db ".read schema-local.sql"

$SQLITE data.db ".read input-data.sql"

python3 populate_size_scores.py

$SQLITE data.db ".read candidates.sql"
$SQLITE data.db ".read run-cost.sql"





