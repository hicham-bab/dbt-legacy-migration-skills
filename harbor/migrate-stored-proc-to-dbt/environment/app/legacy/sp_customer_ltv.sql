-- LEGACY stored procedure to migrate (reference input; Snowflake Scripting dialect).
-- Rebuilds ANALYTICS.CUSTOMER_LTV nightly with a temp table + a full CREATE OR REPLACE.
-- Grain: one row per customer (completed orders only). Segment threshold: lifetime_value >= 150 -> 'high'.
CREATE OR REPLACE PROCEDURE build_customer_ltv()
RETURNS STRING
LANGUAGE SQL
AS
$$
BEGIN
    CREATE OR REPLACE TEMP TABLE _completed AS
        SELECT customer_id, amount
        FROM raw_orders
        WHERE status = 'completed';

    CREATE OR REPLACE TABLE analytics.customer_ltv AS
        SELECT
            customer_id,
            SUM(amount)                                            AS lifetime_value,
            COUNT(*)                                               AS order_count,
            CASE WHEN SUM(amount) >= 150 THEN 'high' ELSE 'low' END AS ltv_segment
        FROM _completed
        GROUP BY customer_id;

    RETURN 'ok';
END;
$$;
