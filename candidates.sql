drop view if exists candidates;

create view candidates as
  with cnt as (select model, uid, count(req_id) as num_runs
                from (models cross join input) left join results_w_model using (model,uid)
             group by model,uid),
       mass as (select model, uid,lower+higher as outside from model_size_scores group by model,uid)
select * from cnt left join mass using (model, uid)
 where (model in ('gpt-5.2', 'gpt-5.3-chat', 'qwen3.5-397b-a17b') and ((num_runs < 5 and outside > 0.2) or (num_runs < 3)))
    or (model = 'gemini-2.5-flash' and num_runs < 2)
    or (model in ('deepseek-v3.2','gpt-oss-120b','qwen3-235b-a22b','llama-4-maverick') and ((num_runs < 12 and outside > 0.2) or (num_runs < 8 and outside > 0) or (num_runs < 5)))
;

select * from candidates limit 0;

