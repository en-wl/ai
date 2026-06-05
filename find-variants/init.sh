set -e

if [ -e data.db ]; then
    echo "data.db exists"
    exit 1
fi

SQLITE="sqlite3 -batch -init ../misc/sqliterc.sql"

$SQLITE data.db ".read schema.sql"
