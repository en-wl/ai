-- Views that depend on the task-specific results table.
-- Load after schema.sql and the task-local schema.

drop view if exists results_w_model;
create view results_w_model as
select model,r.* from results as r join runs using (run_id);

drop view if exists errors_w_model;
create view errors_w_model as
select model, e.* from errors as e join requests using (req_id) join runs using (run_id);

drop view if exists request_cost;
create view request_cost as
select req_id, entry_time, send_time,
       entry_time - send_time as elapsed_secs,
       run_id,
       batch_size as input_rows,
       error is null as success,
       json_extract(response, '$.usage.cost') as usage_cost
from raw_data
join requests using (req_id);
select * from request_cost limit 0;

drop view if exists uid_cost;
create view uid_cost as
select rc.*, output_rows, usage_cost/output_rows as uid_cost
  from request_cost as rc
  left join (select req_id, count(distinct uid) as output_rows
               from results group by req_id) as q using (req_id);
select * from uid_cost limit 0;

drop view if exists run_cost;
create view run_cost as
select run_id, sum(usage_cost) as usage_cost, sum(usage_cost) / sum(output_rows) as uid_cost
from uid_cost
group by run_id;
select * from run_cost limit 0;

drop view if exists runs_w_cost;
create view runs_w_cost as
select r.*, round(usage_cost,4) as usage_cost, round(uid_cost,6) as uid_cost
  from runs as r join run_cost using (run_id);
select * from runs_w_cost limit 0;

