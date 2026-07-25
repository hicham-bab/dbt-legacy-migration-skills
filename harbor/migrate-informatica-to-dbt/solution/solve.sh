#!/usr/bin/env bash
# canary GUID (Terminal-Bench/Harbor convention - keep to prevent training-data contamination):
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

cat > models/staging/_staging.yml <<'YAML'
version: 2
models:
  - name: stg_orders
    description: "Typed passthrough of raw_orders (Source Qualifier SQ_ORDERS)."
    columns:
      - name: order_id
        description: "Order primary key."
        data_tests: [unique, not_null]
YAML

cat > models/marts/_marts.yml <<'YAML'
version: 2
models:
  - name: mart_fct_customer_orders
    description: >
      Customer order fact, migrated from m_FCT_CUSTOMER_ORDERS. Completed orders only, aggregated
      to one row per customer, with a value band (A when lifetime_amount >= 200 else B).
    columns:
      - name: customer_id
        description: "Grain: one row per customer."
        data_tests: [unique, not_null]
      - name: lifetime_amount
        description: "SUM(amount) over completed orders (Aggregator)."
        data_tests: [not_null]
      - name: order_count
        description: "COUNT of completed orders (Aggregator)."
        data_tests: [not_null]
      - name: value_band
        description: "Expression IIF(lifetime_amount >= 200, 'A', 'B')."
        data_tests:
          - accepted_values:
              arguments:
                values: ['A', 'B']
YAML

cat > migration_changes.md <<'MD'
# Migration changes - m_FCT_CUSTOMER_ORDERS (Informatica PowerCenter) -> dbt

| PowerCenter transformation | dbt equivalent |
|---|---|
| Source Qualifier (SQ_ORDERS) | `stg_orders` staging model |
| Filter (`status = 'completed'`) | `completed` CTE |
| Aggregator (SUM/COUNT, group by customer_id) | `agg` CTE |
| Expression (`IIF(lifetime_amount >= 200,'A','B')`) | `banded` CTE (`case ... end as value_band`) |
| Target (FCT_CUSTOMER_ORDERS) | `mart_fct_customer_orders` (table model) |

Grain: one row per customer. Coverage: the single mapping is fully represented as a staging->mart
model family; the 3 modeling transformations map to CTEs within the mart.
MD

export DBT_PROFILES_DIR=/app/project
dbt build
