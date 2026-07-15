-- Sample stored procedure exercising the risky constructs the scanner must flag.
CREATE OR REPLACE PROCEDURE refresh_customer_metrics() RETURNS STRING LANGUAGE SQL AS
$$
DECLARE cutoff DATE;
BEGIN
  cutoff := (SELECT DATEADD(day, -90, CURRENT_DATE()));
  CREATE OR REPLACE TEMP TABLE _recent AS
    SELECT customer_id, amount FROM raw_orders WHERE status = 'completed' AND order_ts >= :cutoff;
  MERGE INTO dim_customer d USING _recent s ON d.customer_id = s.customer_id
    WHEN MATCHED THEN UPDATE SET d.ltv_90d = s.amount
    WHEN NOT MATCHED THEN INSERT (customer_id, ltv_90d) VALUES (s.customer_id, s.amount);
  FOR rec IN (SELECT customer_id FROM dim_customer WHERE last_order_ts < :cutoff) DO
     UPDATE dim_customer SET churn_flag = TRUE WHERE customer_id = rec.customer_id;
  END FOR;
  EXECUTE IMMEDIATE 'ANALYZE TABLE dim_customer';
  RETURN 'ok';
END;
$$;
