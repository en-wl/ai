begin immediate;

-- clean up versions from older version of code
drop table if exists combined;
drop table if exists combined_by_model;

drop table if exists pos_class_cnts_by_model;
drop table if exists pos_cnts_by_model;
drop table if exists lemma_cnts_by_model;
drop table if exists pos_class_cnts;
drop table if exists pos_cnts;
drop table if exists lemma_cnts;
drop table if exists adj_results;
drop table if exists adj_results_by_model;

create table adj_results_by_model (
  uid integer not null,
  model text not null,
  req_id integer not null,
  row_id integer not null,
  pos text,
  pos_class text,
  obscure integer check (obscure in (0, 1))
);

create index adj_results_by_model_uid on adj_results_by_model(uid);

create table adj_results (
  uid integer not null,
  model text not null,
  req_id integer not null,
  row_id integer not null,
  pos text,
  pos_class text,
  obscure integer check (obscure in (0, 1))
);

create index adj_results_uid on adj_results(uid);

create table pos_class_cnts_by_model (
  uid integer not null,
  model text not null,
  pos text not null,
  pos_class text not null,
  cnt integer not null,
  obscure real not null,
  total integer not null,
  primary key (uid, model, pos, pos_class)
) without rowid;

create table pos_cnts_by_model (
  uid integer not null,
  model text not null,
  pos text not null,
  cnt integer not null,
  obscure real not null,
  total integer not null,
  primary key (uid, model, pos)
) without rowid;

create table lemma_cnts_by_model (
  uid integer not null,
  model text not null,
  pos text not null,
  pos_class text not null,
  lemma text not null,
  cnt integer not null,
  total integer not null,
  primary key (uid, model, pos, pos_class, lemma)
) without rowid;

create table pos_class_cnts (
  uid integer not null,
  pos text not null,
  pos_class text not null,
  cnt integer not null,
  cnt_w real not null,
  obscure real not null,
  total integer not null,
  primary key (uid, pos, pos_class)
) without rowid;

create table pos_cnts (
  uid integer not null,
  pos text not null,
  cnt integer not null,
  cnt_w real not null,
  obscure real not null,
  total integer not null,
  primary key (uid, pos)
) without rowid;

create table lemma_cnts (
  uid integer not null,
  pos text not null,
  pos_class text not null,
  lemma text not null,
  cnt integer not null,
  cnt_w real not null,
  total integer not null,
  primary key (uid, pos, pos_class, lemma)
) without rowid;
