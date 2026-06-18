-- Calibration examples (uids 1-16).  Loaded into the `calibration` staging
-- table by init.sh, NOT directly into `input`: init.sh rebuilds `input` from
-- input.tsv (authoritative) plus the calibration pairs that input.tsv lacks.
insert into calibration (uid, noun, plural) values
  (1,'wool','wools'),
  (2,'military','militaries'),
  (3,'weakness','weaknesses'),
  (4,'abnegation','abnegations'),
  (5,'strangeness','strangenesses'),
  (6,'yellowness','yellownesses'),
  (7,'pants','pantses'),
  (8,'building','buildings'),
  (9,'running','runnings'),
  (10,'refusing','refusings'),
  (11,'tuba','tubas'),
  (12,'tuba','tubae'),
  (13,'formula','formulae'),
  (14,'color','colours'),
  (15,'colorize','colorizes'),
  (16,'zgxptk','zgxptks');
