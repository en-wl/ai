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
  start_time real not null, -- unix timestamp with subsecond precision
  batch_size integer not null,
  temperature real not null,
  reasoning_effort text not null, -- 'n/a', 'off', 'none', 'low', etc.
  sample_type text not null -- "random", "continues", "mix", etc
);

create table if not exists requests (
  req_id integer primary key,
  entry_time real not null, -- unix timestamp with subsecond precision
  run_id integer not null,
  batch_size integer not null, -- actual numbers of rows send for this request
  error text, -- error message if the run was aborted, null otherwise
  model_notes text -- notes beyond what is in the table provided by the model
);

create table if not exists raw_data (
  req_id integer primary key,
  request text,
  response text
);

drop view if exists results_w_model;
create view results_w_model as
select model,r.* from results as r join runs using (run_id);

