{{ config(materialized='table', post_hook="delete from {{ this }} where lifetime_value is null") }}
-- Lift-and-shift from Matillion: one monolithic model that reads the raw seed directly (no
-- staging), crams a data-quality DELETE into a post_hook (should be a test), and ships no tests
-- or docs. It builds and returns the right numbers, but it is not idiomatic dbt.
select
    customer_id,
    sum(amount)                                             as lifetime_value,
    count(*)                                                as order_count,
    case when sum(amount) >= 150 then 'high' else 'low' end as ltv_segment
from {{ ref('raw_orders') }}
where status = 'completed'
group by customer_id
