with source as (
    select * from "dev"."main"."raw_orders"
)

select
    cast(order_id as integer)       as order_id,
    cast(customer_id as integer)    as customer_id,
    cast(order_date as date)        as order_date,
    status,
    cast(amount as decimal(18, 2))  as amount
from source