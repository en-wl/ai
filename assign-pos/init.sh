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

$SQLITE data.db ".read test-input.sql"
$SQLITE data.db ".read test-extra.sql"



