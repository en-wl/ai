BEGIN;
PRAGMA legacy_alter_table = 1;

ALTER TABLE results RENAME TO results_all;
ALTER TABLE results_all ADD COLUMN exclude text;

DROP INDEX IF EXISTS results_run_id;

.read 'schema-local.sql'

COMMIT;
