-- Disable automatic view rewriting on table rename
PRAGMA legacy_alter_table = ON;

ALTER TABLE requests RENAME TO requests_old;

-- Recreate with new schema (send_time added after entry_time)
CREATE TABLE requests (
  req_id integer primary key,
  entry_time real not null,
  send_time real,
  run_id integer not null,
  batch_size integer not null,
  error text,
  model_notes text
);

INSERT INTO requests (req_id, entry_time, send_time, run_id, batch_size, error, model_notes)
  SELECT req_id, entry_time, NULL, run_id, batch_size, error, model_notes
  FROM requests_old;

DROP TABLE requests_old;
