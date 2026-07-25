#!/usr/bin/env bash
# canary GUID (Terminal-Bench/Harbor convention - keep to prevent training-data contamination):
# HARBOR-TASK-CANARY d3f1c0a2-migrate-stored-proc-to-dbt
#
# Oracle reference solution: writes the migrated dbt project the way the skill should, so
# `harbor run -a oracle` confirms the task is solvable and the scorecard rewards a correct,
# idiomatic migration (parity + coverage + tests/docs + judge). Kept exemplary on purpose.
set -euo pipefail
cd /app/project

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

# staging: one model per raw source, light typing (proc read raw_orders directly)
cat > models/staging/stg_orders.sql <<'SQL'
select
    cast(order_id as integer)      as order_id,
    cast(customer_id as integer)   as customer_id,
    cast(order_date as date)       as order_date,
    status,
    cast(amount as decimal(18,2))  as amount
from {{ ref('raw_orders') }}
SQL

cat > models/staging/stg_customers.sql <<'SQL'
select
    cast(customer_id as integer) as customer_id,
    customer_name,
    cast(signup_date as date)    as signup_date
from {{ ref('raw_customers') }}
SQL

# mart: migrated from sp_customer_ltv - temp table `_completed` -> CTE; the
# CREATE OR REPLACE TABLE -> a table model. Threshold and grain preserved.
cat > models/marts/mart_customer_ltv.sql <<'SQL'
with completed as (
    select customer_id, amount
    from {{ ref('stg_orders') }}
    where status = 'completed'
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

cat > models/staging/_staging.yml <<'YAML'
version: 2
models:
  - name: stg_orders
    description: "Typed passthrough of raw_orders (source the legacy proc read directly)."
    columns:
      - name: order_id
        description: "Order primary key."
        data_tests: [unique, not_null]
  - name: stg_customers
    description: "Typed passthrough of raw_customers."
    columns:
      - name: customer_id
        description: "Customer primary key."
        data_tests: [unique, not_null]
YAML

cat > models/marts/_marts.yml <<'YAML'
version: 2
models:
  - name: mart_customer_ltv
    description: >
      Customer lifetime value, migrated from sp_customer_ltv. One row per customer over
      completed orders only; ltv_segment is 'high' when lifetime_value >= 150 else 'low'.
    columns:
      - name: customer_id
        description: "Grain: one row per customer."
        data_tests: [unique, not_null]
      - name: lifetime_value
        description: "SUM(amount) over completed orders."
        data_tests: [not_null]
      - name: order_count
        description: "COUNT of completed orders."
        data_tests: [not_null]
      - name: ltv_segment
        description: "high/low bucket at the 150 threshold."
        data_tests:
          - accepted_values:
              arguments:
                values: ['high', 'low']
YAML

cat > migration_changes.md <<'MD'
# Migration changes - sp_customer_ltv -> dbt

| Legacy construct | dbt equivalent |
|---|---|
| `CREATE TEMP TABLE _completed` (completed orders) | `completed` CTE in `mart_customer_ltv` |
| `CREATE OR REPLACE TABLE analytics.customer_ltv` | `mart_customer_ltv` (table model) |
| `raw_orders` direct read | `stg_orders` staging model via `ref()` |
| `SUM(amount)` / `COUNT(*)` / `CASE >= 150` | preserved verbatim in the mart |

Grain: one row per customer (completed orders only). Segment threshold: `lifetime_value >= 150 -> 'high'`.
Coverage: both target-producing statements of the proc are represented. Notify/DDL side-effects: none.
MD

export DBT_PROFILES_DIR=/app/project
dbt build
