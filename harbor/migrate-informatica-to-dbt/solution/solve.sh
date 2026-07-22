#!/usr/bin/env bash
# canary GUID (Terminal-Bench/Harbor convention — keep to prevent training-data contamination):
# HARBOR-TASK-CANARY a9c4d3e6-migrate-informatica-to-dbt
#
# Oracle reference solution: writes the migrated dbt project the way the skill should, so
# `harbor run -a oracle` confirms the task is solvable and the verifier rewards a correct migration.
set -euo pipefail
cd /app/project

mkdir -p seeds models/staging models/marts
cp /app/data/raw_orders.csv seeds/raw_orders.csv

cat > dbt_project.yml <<'YAML'
name: informatica_demo
version: 1.0.0
profile: informatica_demo
require-dbt-version: [">=1.9.0"]
model-paths: ["models"]
seed-paths: ["seeds"]
YAML

# Source Qualifier -> staging (rename/cast)
cat > models/staging/stg_orders.sql <<'SQL'
select
    cast(order_id as integer)     as order_id,
    cast(customer_id as integer)  as customer_id,
    cast(order_date as date)      as order_date,
    status,
    cast(amount as decimal(18,2)) as amount
from {{ ref('raw_orders') }}
SQL

# FIL_COMPLETED -> WHERE; AGG_CUSTOMER -> GROUP BY; EXP_BAND -> CASE (IIF >= 200 -> 'A' else 'B').
cat > models/marts/mart_fct_customer_orders.sql <<'SQL'
with completed as (
    select customer_id, order_id, amount from {{ ref('stg_orders') }} where status = 'completed'
),
agg as (
    select
        customer_id,
        cast(sum(amount) as decimal(18,2)) as lifetime_amount,
        count(order_id)                    as order_count
    from completed
    group by customer_id
),
banded as (
    select
        customer_id,
        lifetime_amount,
        order_count,
        case when lifetime_amount >= 200 then 'A' else 'B' end as value_band
    from agg
)
select * from banded
SQL

export DBT_PROFILES_DIR=/app/project
dbt build
