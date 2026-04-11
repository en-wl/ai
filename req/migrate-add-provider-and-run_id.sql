-- Migration: add runs.provider and raw_data.run_id.
-- Run from a task directory that contains data.db, e.g.:
--   sqlite3 -batch -init ../misc/sqliterc.sql data.db \
--       < ../req/migrate-add-provider-and-run_id.sql

begin;

PRAGMA legacy_alter_table = ON;

ALTER TABLE runs     RENAME TO runs_old;
ALTER TABLE raw_data RENAME TO raw_data_old;

-- Recreate runs and raw_data with their new shape from schema.sql.
.read ../req/schema.sql

-- runs.provider is new; existing rows get NULL.
INSERT INTO runs (run_id, model, provider, start_time, batch_size,
                  temperature, reasoning_effort, sample_type)
  SELECT run_id, model, NULL, start_time, batch_size,
         temperature, reasoning_effort, sample_type
  FROM runs_old;

-- raw_data.run_id is new and NOT NULL; backfill from requests.
INSERT INTO raw_data (req_id, run_id, request, response)
  SELECT rd.req_id, r.run_id, rd.request, rd.response
  FROM raw_data_old rd JOIN requests r USING (req_id);

DROP TABLE runs_old;
DROP TABLE raw_data_old;

commit;

