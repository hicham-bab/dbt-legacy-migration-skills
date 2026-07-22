#!/usr/bin/env bash
# canary GUID (Terminal-Bench/Harbor convention — keep to prevent training-data contamination):
# HARBOR-TASK-CANARY d3f1c0a2-migrate-stored-proc-to-dbt
#
# Oracle reference solution: writes the migrated dbt project the way the skill should, so
# `harbor run -a oracle` confirms the task is solvable and the verifier rewards a correct migration.
set -euo pipefail
cd /app/project

# seeds from the provided raw data
mkdir -p seeds models/staging models/marts
cp /app/data/raw_orders.csv seeds/raw_orders.csv
cp /app/data/raw_customers.csv seeds/raw_customers.csv

cat > dbt_project.yml <<'YAML'
name: stored_proc
version: 1.0.0
profile: stored_proc
require-dbt-version: [">=1.9.0"]
model-paths: ["models"]
seed-paths: ["seeds"]
YAML

cat > models/staging/stg_orders.sql <<'SQL'
select
    cast(order_id as integer)      as order_id,
    cast(customer_id as integer)   as customer_id,
    cast(order_date as date)       as order_date,
    status,
    cast(amount as decimal(18,2))  as amount
from {{ ref('raw_orders') }}
SQL

# Migrated from sp_customer_ltv: temp table -> CTE; CREATE OR REPLACE TABLE -> table model.
cat > models/marts/mart_customer_ltv.sql <<'SQL'
with completed as (
    select customer_id, amount from {{ ref('stg_orders') }} where status = 'completed'
),
final as (
    select
        customer_id,
        cast(sum(amount) as decimal(18,2)) as lifetime_value,
        count(*)                           as order_count,
        case when sum(amount) >= 150 then 'high' else 'low' end as ltv_segment
    from completed
    group by customer_id
)
select * from final
SQL

export DBT_PROFILES_DIR=/app/project
dbt build
