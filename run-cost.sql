drop view if exists request_cost;
create view request_cost as
select req_id, entry_time, run_id, 
       batch_size as input_rows, 
       error is null as success,
       json_extract(response, '$.usage.cost') as usage_cost
from raw_data
join requests using (req_id);

drop view if exists row_cost;
create view row_cost as
select rc.*, output_rows, usage_cost/output_rows as row_cost
  from request_cost as rc
  left join (select req_id, count(distinct uid) as output_rows
               from results group by req_id) as q using (req_id);

drop view if exists run_cost;
create view run_cost as
select run_id, sum(usage_cost) as usage_cost, sum(usage_cost) / sum(output_rows) as row_cost
from row_cost
group by run_id;

drop view if exists runs_w_cost;
create view runs_w_cost as
select r.*, round(usage_cost,4) as usage_cost, round(row_cost,6) as row_cost
  from runs as r join run_cost using (run_id);
