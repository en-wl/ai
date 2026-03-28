create table if not exists input (
  uid integer primary key,
  lemmas text not null,
  pos not null
);

create table if not exists model_size_scores (
  uid integer not null,
  pos text not null,
  model text not null,
  size integer not null,
  lower real not null,
  higher real not null,
  s_60 real not null,
  s_70 real not null,
  s_80 real not null,
  s_99 real not null,
  primary key (uid, pos, model)
) without rowid;

create table if not exists results (
  uid integer not null,
  run_id integer not null,
  req_id integer not null,
  lemmas text not null,
  pos text not null,
  size integer not null check (size in (60, 70, 80, 99)),
  borderline text not null check (borderline in ('', '60/70', '70/80', '80/99')),
  size_notes text not null,
  primary key (uid, req_id)
) without rowid;
