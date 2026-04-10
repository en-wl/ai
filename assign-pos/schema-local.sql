create table if not exists input (
  uid integer primary key,
  word text not null,
  pos not null
);

create table if not exists results_all (
  row_id integer primary key,
  uid integer not null,
  run_id integer not null,
  req_id integer not null,
  word text not null,
  lemma text not null,
  pos text not null,
  pos_class text not null,
  notes text not null,
  exclude text,
  unique (uid, pos, pos_class, req_id)
);

-- Partial covering index: only non-excluded rows, matching the view filter.
-- Keeps the index covering for the critical candidates query
-- (SELECT uid, count(distinct req_id) ... WHERE run_id = ? GROUP BY uid).
drop index if exists results_run_id;
create index results_run_id
  on results_all(run_id, uid, req_id) where exclude is null;

-- Index to make sure results_run_id is used
drop index if exists runs_model;
create index runs_model ON runs(model);

-- View: drop-in replacement for old results table
drop view if exists results;
create view results as
select row_id, uid, run_id, req_id, word, lemma, pos, pos_class, notes
  from results_all
 where exclude is null;

-- INSTEAD OF triggers so DML on the view works transparently
create trigger results_insert
instead of insert on results
begin
  insert into results_all (uid, run_id, req_id, word, lemma, pos, pos_class, notes)
  values (NEW.uid, NEW.run_id, NEW.req_id, NEW.word, NEW.lemma, NEW.pos,
          NEW.pos_class, NEW.notes);
end;

drop index if exists results_run_id;
create index results_run_id
  on results_all(run_id, uid, req_id) where exclude is null;

-- View: drop-in replacement for old results table
drop view if exists results;
create view results as
select row_id, uid, run_id, req_id, word, lemma, pos, pos_class, notes
  from results_all
 where exclude is null;

-- INSTEAD OF triggers so DML on the view works transparently
create trigger results_insert
instead of insert on results
begin
  insert into results_all (uid, run_id, req_id, word, lemma, pos, pos_class, notes)
  values (NEW.uid, NEW.run_id, NEW.req_id, NEW.word, NEW.lemma, NEW.pos,
          NEW.pos_class, NEW.notes);
end;
create trigger results_delete
instead of delete on results
begin
  delete from results_all where row_id = OLD.row_id;
end;
create trigger results_update
instead of update on results
begin
  update results_all
     set uid = NEW.uid, run_id = NEW.run_id, req_id = NEW.req_id,
         word = NEW.word, lemma = NEW.lemma, pos = NEW.pos,
         pos_class = NEW.pos_class, notes = NEW.notes
   where row_id = OLD.row_id;
end;
