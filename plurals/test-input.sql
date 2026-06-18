-- Calibration examples (embedded instruction-following check).  Loaded into the
-- `calibration` staging table by populate.sh, NOT directly into `input`:
-- populate.sh assigns uids (in the 1-19 block) and silently skips any pair an
-- earlier source (input.tsv) already claimed, so a pair is never sent to the
-- model twice.  Keyed by (noun,plural) -- no uids here; gold.sql / test-parse.py
-- recover the live uid via (noun,plural).
insert into calibration (noun, plural) values
  ('wool','wools'),
  ('military','militaries'),
  ('matrix','matrices'),
  ('weakness','weaknesses'),
  ('music','musics'),
  ('knowledge','knowledges'),
  ('abnegation','abnegations'),
  ('strangeness','strangenesses'),
  ('yellowness','yellownesses'),
  ('pants','pantses'),
  ('building','buildings'),
  ('running','runnings'),
  ('refusing','refusings'),
  ('tuba','tubas'),
  ('tuba','tubae'),
  ('formula','formulae'),
  ('color','colours'),
  ('colorize','colorizes'),
  ('zgxptk','zgxptks');
