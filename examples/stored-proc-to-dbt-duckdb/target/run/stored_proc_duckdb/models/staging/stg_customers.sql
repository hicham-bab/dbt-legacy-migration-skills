
  
  create view "dev"."main"."stg_customers__dbt_tmp" as (
    with source as (
    select * from "dev"."main"."raw_customers"
)

select
    cast(customer_id as integer) as customer_id,
    customer_name,
    cast(signup_date as date)    as signup_date
from source
  );
