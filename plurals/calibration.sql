-- Calibration examples (embedded instruction-following check) with expected
-- classification.  Keyed by (noun,plural) -- no uids here.
--
-- Must be less then 20 entries to fit in the uid range 1-19.
--
-- `category` is the base category and `rare_form` the boolean.  combine.py
-- tracks category and rare_form independently: category_top/category_top_by_model
-- carry the top category only, while rare_wavg/rare_by_model carry the rare-form
-- score/fraction.  The combined category check compares category only:
--
--   select i.uid, g.noun, g.plural,
--          g.category as expected, t.category as got, t.score
--     from calibration g
--     join input i using (noun, plural)
--     join category_top t using (uid)
--    where g.category <> t.category;
--
-- Per-model category check:
--   select i.uid, g.noun, g.plural, t.model,
--          g.category as expected, t.category as got
--     from calibration g
--     join input i using (noun, plural)
--     join category_top_by_model t using (uid)
--    where g.category <> t.category;
--
-- Rare-form check (combined score; per-model via rare_by_model.frac):
--   select i.uid, g.noun, g.plural, g.rare_form as expected, r.score as got
--     from calibration g
--     join input i using (noun, plural)
--     join rare_wavg r using (uid);

create table if not exists calibration (
  noun text not null,
  plural text not null,
  category text not null,
  rare_form integer not null,
  primary key (noun, plural)
);

insert into calibration (noun, plural, category, rare_form) values
  ('wool','wools','natural',0),
  ('military','militaries','natural',0),
  ('hyperplane','hyperplanes','natural',0),
  ('weakness','weaknesses','natural',0),
  ('toothpaste', 'toothpastes', 'specialized', 0),
  ('music','musics','specialized',0),
  ('knowledge','knowledges','specialized',0),
  ('abnegation','abnegations','contrived',0),
  ('strangeness','strangenesses','contrived',0),
  ('yellowness','yellownesses','contrived',0),
  ('pants','pantses','ungrammatical',0),
  ('building','buildings','natural',0),
  ('running','runnings','contrived',0),
  ('refusing','refusings','gerund',0),
--('tuba','tubas','natural',0),
  ('tuba','tubae','natural',1),
  ('formula','formulae','natural',0),
  ('color','colours','invalid',0),
  ('colorize','colorizes','invalid',0),
  ('zgxptk','zgxptks','invalid',0);

