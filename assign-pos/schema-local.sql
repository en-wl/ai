create table if not exists input (
  uid integer primary key,
  word text not null,
  pos not null
);

create table if not exists results (
  uid integer not null,
  run_id integer not null,
  req_id integer not null,
  word text not null,
  lemma text not null,
  pos text not null,
  pos_class text not null,
  notes text not null,
  primary key (uid, pos, pos_class, req_id)
) without rowid;

