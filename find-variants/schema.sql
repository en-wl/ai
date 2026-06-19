.once /dev/null
pragma journal_mode = wal;

create table if not exists models (
  model text primary key
) without rowid;

create table if not exists runs (
  run_id integer primary key,
  model text not null,
  provider text, -- null if request went through openrouter
  start_time real not null, -- unix timestamp with subsecond precision
  batch_size integer not null,
  temperature real not null,
  reasoning_effort text not null, -- 'n/a', 'off', 'none', 'low', etc.
  sample_type text not null -- "random", "continues", "mix", etc
  note text,
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

create table if not exists results (
  row_id integer primary key,
  req_id integer not null,
  run_id integer not null,
  label text,
  word text not null,
  variant_label text,
  variant text,
  qualifier text,
  notes text
);

-- Required by req/_manager.py (run_id assignment + stale cleanup). Not
-- otherwise used here: find-variants runs a single pass, no dynamic mode.
create table if not exists outstanding_runs (
  run_id integer primary key,
  timestamp real not null,
  state text not null check (state in ('active', 'waiting', 'wakeup', 'done'))
);

create table if not exists outstanding_reqs (
  uid integer not null,
  model text not null,
  run_id integer not null,
  seq_id integer not null,
  timestamp real not null,
  primary key (run_id, seq_id, uid)
) without rowid;

drop view if exists results_w_model;
create view results_w_model as
select model,r.* from results as r join runs using (run_id);

drop view if exists request_cost;
create view request_cost as
select rd.req_id, entry_time, send_time,
       entry_time - send_time as elapsed_secs,
       rd.run_id,
       batch_size as input_uids,
       error is null as success,
       json_extract(response, '$.usage.cost') as usage_cost
from raw_data as rd
join requests using (req_id);
select * from request_cost limit 0;
