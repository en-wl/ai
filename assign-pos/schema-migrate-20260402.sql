BEGIN;

PRAGMA legacy_alter_table = 1;

ALTER TABLE results RENAME TO results_old;

.read 'schema-local.sql'

INSERT INTO results (uid, run_id, req_id, word, lemma, pos, pos_class, notes)
SELECT uid, run_id, req_id, word, lemma, pos, pos_class, notes
FROM results_old
ORDER BY req_id, uid, pos, pos_class, lemma;

DROP TABLE results_old;

COMMIT;
