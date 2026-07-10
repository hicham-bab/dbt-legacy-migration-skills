
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  -- PARITY GATE (singular test): the migrated mart must match the legacy proc output row-for-row.
-- dbt fails the build if this returns any rows. This is the "prove it's correct" step, running
-- for real on DuckDB — the legacy output is captured as the seed legacy_customer_ltv.
with dbt_model as (
    select * from "dev"."main"."mart_customer_ltv"
),

legacy as (
    select * from "dev"."main"."legacy_customer_ltv"
),

compared as (
    select
        coalesce(d.customer_id, l.customer_id) as customer_id,
        case
            when d.customer_id is null then 'missing_in_dbt'
            when l.customer_id is null then 'missing_in_legacy'
            when round(cast(d.lifetime_value as double), 2)
               <> round(cast(l.lifetime_value as double), 2) then 'lifetime_value_mismatch'
            when cast(d.order_count as integer) <> cast(l.order_count as integer) then 'order_count_mismatch'
            when d.ltv_segment <> l.ltv_segment then 'segment_mismatch'
        end as diff
    from dbt_model d
    full outer join legacy l on d.customer_id = l.customer_id
)

select * from compared
where diff is not null
  
  
      
    ) dbt_internal_test