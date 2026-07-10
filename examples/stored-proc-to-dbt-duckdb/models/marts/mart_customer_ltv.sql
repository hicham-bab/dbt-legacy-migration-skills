-- Migrated from legacy/sp_customer_ltv.sql: the procedural temp-table rebuild becomes a
-- declarative model on ref() staging models. Same output, same grain (one row per customer).
with completed as (
    select customer_id, amount
    from {{ ref('stg_orders') }}
    where status = 'completed'
),

final as (
    select
        customer_id,
        cast(sum(amount) as decimal(18, 2)) as lifetime_value,
        count(*)                            as order_count,
        case when sum(amount) >= 150 then 'high' else 'low' end as ltv_segment
    from completed
    group by customer_id
)

select * from final
