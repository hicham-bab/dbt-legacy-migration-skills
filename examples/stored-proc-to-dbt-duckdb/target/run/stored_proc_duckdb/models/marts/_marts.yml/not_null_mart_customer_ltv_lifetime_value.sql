
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select lifetime_value
from "dev"."main"."mart_customer_ltv"
where lifetime_value is null



  
  
      
    ) dbt_internal_test