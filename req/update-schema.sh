#!/bin/sh
set -e
SQLITE="sqlite3 -batch -init ../misc/sqliterc.sql"
$SQLITE data.db ".read ../req/schema.sql"
$SQLITE data.db ".read schema-local.sql"
$SQLITE data.db ".read ../req/post.sql"
