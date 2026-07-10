
    
    

with all_values as (

    select
        ltv_segment as value_field,
        count(*) as n_records

    from "dev"."main"."mart_customer_ltv"
    group by ltv_segment

)

select *
from all_values
where value_field not in (
    'high','low'
)


