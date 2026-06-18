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

-- ESDB reference data (loaded from sample-input.tsv by populate.sh).  The
-- (noun,plural) pairs are also imported into `input`; `category` is ESDB's
-- already-determined classification, kept here to later check how well the
-- models' verdicts align (join category_top -> input using(uid) -> sample
-- using(noun,plural)).
create table if not exists sample (
  noun text not null,
  plural text not null,
  category text not null,
  primary key (noun, plural)
);
