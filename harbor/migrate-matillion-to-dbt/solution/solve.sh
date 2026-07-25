#!/usr/bin/env bash
# canary GUID (Terminal-Bench/Harbor convention - keep to prevent training-data contamination):
# HARBOR-TASK-CANARY b4e7a1c9-migrate-matillion-to-dbt
#
# Oracle reference solution: writes the migrated dbt project the way the skill should, so
# `harbor run -a oracle` confirms the task is solvable and the scorecard rewards a correct,
# idiomatic migration (parity + coverage + tests/docs + judge). Kept exemplary on purpose.
set -euo pipefail
cd /app/project

mkdir -p seeds models/staging models/intermediate models/marts
cp /app/data/raw_orders.csv    seeds/raw_orders.csv
cp /app/data/raw_customers.csv seeds/raw_customers.csv

cat > dbt_project.yml <<'YAML'
name: matillion_demo
version: 1.0.0
profile: matillion_demo
require-dbt-version: [">=1.9.0"]
model-paths: ["models"]
seed-paths: ["seeds"]
YAML

# table-input -> staging models
cat > models/staging/stg_orders.sql <<'SQL'
select
    cast(order_id as integer)         as order_id,
    cast(customer_id as integer)      as customer_id,
    cast(order_date as date)          as order_date,
    status,
    cast(total_amount as decimal(18,2))    as total_amount,
    cast(discount_amount as decimal(18,2)) as discount_amount
from {{ ref('raw_orders') }}
SQL

cat > models/staging/stg_customers.sql <<'SQL'
select
    cast(customer_id as integer) as customer_id,
    customer_name,
    region,
    segment
from {{ ref('raw_customers') }}
SQL

# calculator (net_amount) + filter (completed) -> intermediate, reused by both marts
cat > models/intermediate/int_completed_orders.sql <<'SQL'
select
    order_id,
    customer_id,
    order_date,
    total_amount,
    discount_amount,
    cast(total_amount - discount_amount as decimal(18,2)) as net_amount
from {{ ref('stg_orders') }}
where status = 'completed'
SQL

# join + rank -> fct_orders (one row per completed order)
cat > models/marts/mart_fct_orders.sql <<'SQL'
select
    o.order_id,
    o.customer_id,
    o.order_date,
    o.net_amount,
    c.customer_name,
    c.region,
    c.segment,
    row_number() over (partition by o.customer_id order by o.order_date desc) as order_recency_rank
from {{ ref('int_completed_orders') }} o
left join {{ ref('stg_customers') }} c using (customer_id)
SQL

# aggregate -> agg_customer_sales (one row per customer)
cat > models/marts/mart_agg_customer_sales.sql <<'SQL'
select
    customer_id,
    cast(sum(net_amount) as decimal(18,2)) as total_net,
    count(order_id)                        as order_count
from {{ ref('int_completed_orders') }}
group by customer_id
SQL

cat > models/staging/_staging.yml <<'YAML'
version: 2
models:
  - name: stg_orders
    description: "Typed passthrough of raw_orders (table-input 'Read orders')."
    columns:
      - name: order_id
        description: "Order primary key."
        data_tests: [unique, not_null]
  - name: stg_customers
    description: "Typed passthrough of raw_customers (table-input 'Read customers')."
    columns:
      - name: customer_id
        description: "Customer primary key."
        data_tests: [unique, not_null]
YAML

cat > models/intermediate/_intermediate.yml <<'YAML'
version: 2
models:
  - name: int_completed_orders
    description: >
      Completed orders with net_amount = total_amount - discount_amount. Migrates the Matillion
      'Compute net amount' (calculator) and 'Completed only' (filter) components; reused by both marts.
    columns:
      - name: order_id
        description: "Order primary key."
        data_tests: [unique, not_null]
YAML

cat > models/marts/_marts.yml <<'YAML'
version: 2
models:
  - name: mart_fct_orders
    description: >
      One row per completed order, joined to customer attributes, with order_recency_rank from the
      Matillion 'Rank recent per customer' component (row_number over customer_id by order_date desc).
    columns:
      - name: order_id
        description: "Grain: one row per completed order."
        data_tests: [unique, not_null]
      - name: order_recency_rank
        description: "row_number() partition by customer_id order by order_date desc."
        data_tests: [not_null]
  - name: mart_agg_customer_sales
    description: >
      One row per customer: total_net = SUM(net_amount), order_count = COUNT(order_id). Migrates the
      Matillion 'Aggregate by customer' component.
    columns:
      - name: customer_id
        description: "Grain: one row per customer."
        data_tests: [unique, not_null]
      - name: total_net
        description: "SUM(net_amount) over completed orders."
        data_tests: [not_null]
YAML

cat > migration_changes.md <<'MD'
# Migration changes - build_sales_marts (Matillion) -> dbt

| Matillion component | dbt equivalent |
|---|---|
| table-input `Read orders` / `Read customers` | `stg_orders` / `stg_customers` |
| calculator `Compute net amount` | `net_amount` column in `int_completed_orders` |
| filter `Completed only` | `where status = 'completed'` in `int_completed_orders` |
| join `Join customer` (LEFT) | `left join stg_customers using (customer_id)` in `mart_fct_orders` |
| rank `Rank recent per customer` (row_number) | `row_number() over (...)` in `mart_fct_orders` |
| aggregate `Aggregate by customer` | `mart_agg_customer_sales` (SUM/COUNT group by customer) |
| rewrite-table `Write fct_orders` | `mart_fct_orders` (table model) |
| table-output `Write agg_customer_sales` | `mart_agg_customer_sales` (table model) |

Grain: `mart_fct_orders` = one completed order; `mart_agg_customer_sales` = one customer.
Coverage: all transformation components represented across staging -> intermediate -> marts.
MD

export DBT_PROFILES_DIR=/app/project
dbt build
