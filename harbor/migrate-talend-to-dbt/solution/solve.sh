#!/usr/bin/env bash
# canary GUID (Terminal-Bench/Harbor convention — keep to prevent training-data contamination):
# HARBOR-TASK-CANARY 7b2e9f14-migrate-talend-to-dbt
#
# Oracle reference solution: writes the migrated dbt project the way the skill should, so
# `harbor run -a oracle` confirms the task is solvable and the verifier rewards a correct migration.
set -euo pipefail
cd /app/project

mkdir -p seeds models/staging models/marts
cp /app/data/raw_orders.csv    seeds/raw_orders.csv
cp /app/data/raw_customers.csv seeds/raw_customers.csv

cat > dbt_project.yml <<'YAML'
name: talend_demo
version: 1.0.0
profile: talend_demo
require-dbt-version: [">=1.9.0"]
model-paths: ["models"]
seed-paths: ["seeds"]
YAML

# tPostgresqlInput -> staging models (rename/cast)
cat > models/staging/stg_orders.sql <<'SQL'
select
    cast(order_id as integer)     as order_id,
    cast(customer_id as integer)  as customer_id,
    cast(order_date as date)      as order_date,
    status,
    cast(amount as decimal(18,2)) as amount
from {{ ref('raw_orders') }}
SQL

cat > models/staging/stg_customers.sql <<'SQL'
select
    cast(customer_id as integer) as customer_id,
    customer_name
from {{ ref('raw_customers') }}
SQL

# tFilterRow(completed) -> WHERE; tMap(INNER JOIN) -> join; tAggregateRow -> GROUP BY.
cat > models/marts/mart_customer_revenue.sql <<'SQL'
with completed as (
    select customer_id, amount from {{ ref('stg_orders') }} where status = 'completed'
),
joined as (
    select o.customer_id, c.customer_name, o.amount
    from completed o
    join {{ ref('stg_customers') }} c using (customer_id)
),
agg as (
    select
        customer_id,
        customer_name,
        cast(sum(amount) as decimal(18,2)) as total_revenue,
        count(*)                           as order_count
    from joined
    group by customer_id, customer_name
)
select * from agg
SQL

export DBT_PROFILES_DIR=/app/project
dbt build
