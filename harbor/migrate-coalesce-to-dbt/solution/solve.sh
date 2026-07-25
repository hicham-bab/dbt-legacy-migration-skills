#!/usr/bin/env bash
# canary GUID (Terminal-Bench/Harbor convention - keep to prevent training-data contamination):
# HARBOR-TASK-CANARY c7f2b6d4-migrate-coalesce-to-dbt
#
# Oracle reference solution: writes the migrated dbt project the way the skill should, so
# `harbor run -a oracle` confirms the task is solvable and the scorecard rewards a correct,
# idiomatic migration (parity + coverage + tests/docs + judge). The Type 2 Coalesce dimension
# becomes a dbt snapshot. Kept exemplary on purpose.
set -euo pipefail
cd /app/project

mkdir -p seeds models/staging models/marts snapshots
cp /app/data/raw_customer.csv seeds/raw_customer.csv
cp /app/data/raw_nation.csv   seeds/raw_nation.csv
cp /app/data/raw_orders.csv   seeds/raw_orders.csv

cat > dbt_project.yml <<'YAML'
name: coalesce_demo
version: 1.0.0
profile: coalesce_demo
require-dbt-version: [">=1.9.0"]
model-paths: ["models"]
seed-paths: ["seeds"]
snapshot-paths: ["snapshots"]
YAML

# Coalesce Stage nodes -> staging models
cat > models/staging/stg_customer.sql <<'SQL'
select
    cast(c_custkey as integer)  as c_custkey,
    c_name,
    cast(c_nationkey as integer) as c_nationkey,
    c_mktsegment
from {{ ref('raw_customer') }}
SQL

cat > models/staging/stg_nation.sql <<'SQL'
select
    cast(n_nationkey as integer) as n_nationkey,
    n_name
from {{ ref('raw_nation') }}
SQL

cat > models/staging/stg_orders.sql <<'SQL'
select
    cast(o_orderkey as integer)  as o_orderkey,
    cast(o_custkey as integer)   as o_custkey,
    o_orderstatus,
    cast(o_totalprice as decimal(12,2)) as o_totalprice
from {{ ref('raw_orders') }}
SQL

# Coalesce Dimension (Type 2, change-tracking on C_NAME) -> dbt snapshot (check strategy)
cat > snapshots/customer_snapshot.sql <<'SQL'
{% snapshot customer_snapshot %}
{{ config(unique_key='c_custkey', strategy='check', check_cols=['c_name']) }}
select * from {{ ref('stg_customer') }}
{% endsnapshot %}
SQL

# Current view of the dimension + surrogate key + nation join
cat > models/marts/mart_dim_customer.sql <<'SQL'
with current_customers as (
    select c_custkey, c_name, c_nationkey, c_mktsegment
    from {{ ref('customer_snapshot') }}
    where dbt_valid_to is null
)
select
    row_number() over (order by cc.c_custkey) as dim_customer_key,
    cc.c_custkey,
    cc.c_name,
    n.n_name as nation_name,
    cc.c_mktsegment
from current_customers cc
left join {{ ref('stg_nation') }} n on cc.c_nationkey = n.n_nationkey
SQL

# Fact at order grain, FK to the customer dimension
cat > models/marts/mart_fct_orders.sql <<'SQL'
select
    o.o_orderkey,
    d.dim_customer_key,
    o.o_orderstatus,
    o.o_totalprice
from {{ ref('stg_orders') }} o
left join {{ ref('mart_dim_customer') }} d on o.o_custkey = d.c_custkey
SQL

cat > models/staging/_staging.yml <<'YAML'
version: 2
models:
  - name: stg_customer
    description: "Staged customers (Coalesce STG_CUSTOMER)."
    columns:
      - name: c_custkey
        description: "Customer business key."
        data_tests: [unique, not_null]
  - name: stg_nation
    description: "Staged nations (Coalesce STG_NATION)."
    columns:
      - name: n_nationkey
        description: "Nation key."
        data_tests: [unique, not_null]
  - name: stg_orders
    description: "Staged orders (Coalesce STG_ORDERS)."
    columns:
      - name: o_orderkey
        description: "Order business key."
        data_tests: [unique, not_null]
YAML

cat > models/marts/_marts.yml <<'YAML'
version: 2
models:
  - name: mart_dim_customer
    description: >
      Customer dimension migrated from the Coalesce Type 2 DIM_CUSTOMER node. Current view over the
      customer_snapshot (change-tracking on c_name), with a surrogate key and nation name.
    columns:
      - name: dim_customer_key
        description: "Surrogate key: row_number over c_custkey."
        data_tests: [unique, not_null]
      - name: c_custkey
        description: "Business key (grain: one row per current customer)."
        data_tests: [unique, not_null]
      - name: nation_name
        description: "Joined from stg_nation on nationkey."
        data_tests: [not_null]
  - name: mart_fct_orders
    description: >
      Order fact migrated from the Coalesce FCT_ORDERS node. One row per order, with the
      dim_customer_key looked up from mart_dim_customer.
    columns:
      - name: o_orderkey
        description: "Grain: one row per order."
        data_tests: [unique, not_null]
      - name: dim_customer_key
        description: "FK to mart_dim_customer."
        data_tests: [not_null]
YAML

cat > migration_changes.md <<'MD'
# Migration changes - Coalesce project -> dbt

| Coalesce node (sqlType) | dbt equivalent |
|---|---|
| CUSTOMER / NATION / ORDERS (Source) | seeds `raw_customer` / `raw_nation` / `raw_orders` |
| STG_CUSTOMER / STG_NATION / STG_ORDERS (Stage) | `stg_customer` / `stg_nation` / `stg_orders` |
| DIM_CUSTOMER (Dimension, **Type 2** on C_NAME) | **snapshot** `customer_snapshot` (check strategy on c_name) + `mart_dim_customer` current view |
| FCT_ORDERS (Fact) | `mart_fct_orders` (order grain, FK to dim) |

The Type 2 change-tracking column (`c_name`) maps to a dbt snapshot `check_cols`. Surrogate key
`dim_customer_key` = row_number over `c_custkey`. Coverage: all 5 non-source nodes represented.
MD

export DBT_PROFILES_DIR=/app/project
dbt build
