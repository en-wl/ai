create table if not exists input (
  uid integer primary key,
  noun text not null,
  plural text not null
);

create table if not exists results (
  row_id integer primary key,
  uid integer not null,
  run_id integer not null,
  req_id integer not null,
  plural text not null,
  category text not null,
  notes text not null,
  unique (uid, req_id)
);
