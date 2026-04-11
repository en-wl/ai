.once /dev/null
pragma journal_mode = wal;

create table if not exists models (
  model text primary key
) without rowid;

create table if not exists errors (
  req_id integer not null,
  uid integer, -- null unless the uid is verifed to be in the request 
  error_code text not null,
  error_msg text not null,
  orig_line text
);

create table if not exists runs (
  run_id integer primary key,
  model text not null,
  provider text, -- null if request went through openrouter
  start_time real not null, -- unix timestamp with subsecond precision
  batch_size integer not null,
  temperature real not null,
  reasoning_effort text not null, -- 'n/a', 'off', 'none', 'low', etc.
  sample_type text not null -- "random", "continues", "mix", etc
);

create table if not exists requests (
  req_id integer primary key,
  entry_time real not null, -- unix timestamp with subsecond precision
  send_time real,           -- unix timestamp: just before http_session.post() — NULL for old rows
  run_id integer not null,
  batch_size integer not null, -- actual numbers of rows send for this request
  error text, -- error message if the run was aborted, null otherwise
  model_notes text -- notes beyond what is in the table provided by the model
);

create table if not exists raw_data (
  req_id integer primary key,
  run_id integer not null,
  request text,
  response text
);

drop table if exists outstanding_runs;
create table outstanding_runs (
  run_id integer primary key,
  timestamp real not null,
  state text not null check (state in ('active',   -- actively processing uids
                                       'waiting',  -- waiting for other runs to finish
                                       'wakeup',   -- other runs finish, processing reaming uids
                                       'done'))    -- no more uids to process at this time
);

drop table if exists outstanding_reqs;
create table outstanding_reqs (
  uid integer not null,
  model text not null,
  run_id integer not null,
  seq_id integer not null,
  timestamp real not null,
  primary key (run_id, seq_id, uid)
) without rowid;

drop table if exists completed_reqs;
create table completed_reqs (
  uid integer not null,
  model text not null,
  run_id integer not null,
  primary key (run_id, uid)
) without rowid;

create table if not exists skipped_uids (
  uid integer not null,
  run_id integer not null,
  primary key (uid, run_id)
) without rowid;
