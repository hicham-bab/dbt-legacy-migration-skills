#!/usr/bin/env bash
# canary GUID (Terminal-Bench/Harbor convention - keep to prevent training-data contamination):
# HARBOR-TASK-CANARY e9a1c7b3-remediate-lift-and-shift-to-dbt
#
# Oracle: refactors the lift-and-shift project in /app/project into idiomatic dbt WITHOUT changing
# results, so `harbor run -a oracle` confirms the task is solvable and the scorecard rewards a
# refactor that keeps parity AND clears the anti-pattern linter (require_lint).
set -euo pipefail
cd /app/project
mkdir -p models/staging models/marts

# add the staging layer the lift-and-shift skipped
cat > models/staging/stg_orders.sql <<'SQL'
select
    cast(order_id as integer)     as order_id,
    cast(customer_id as integer)  as customer_id,
    cast(order_date as date)      as order_date,
    status,
    cast(amount as decimal(18,2)) as amount
from {{ ref('raw_orders') }}
SQL

# rebuild the mart idiomatically: reads staging via ref(), no post_hook, same grain and logic
cat > models/marts/customer_ltv.sql <<'SQL'
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

cat > models/staging/_staging.yml <<'YAML'
version: 2
models:
  - name: stg_orders
    description: "Typed passthrough of raw_orders (added in remediation; the lift-and-shift skipped staging)."
    columns:
      - name: order_id
        description: "Order primary key."
        data_tests: [unique, not_null]
YAML

cat > models/marts/_marts.yml <<'YAML'
version: 2
models:
  - name: customer_ltv
    description: >
      Customer lifetime value over completed orders. Remediated from a lift-and-shift monolith:
      staging extracted, post_hook removed, tests and docs added; results unchanged.
    columns:
      - name: customer_id
        description: "Grain: one row per customer."
        data_tests: [unique, not_null]
      - name: lifetime_value
        description: "SUM(amount) over completed orders."
        data_tests: [not_null]
      - name: ltv_segment
        description: "high/low bucket at the 150 threshold."
        data_tests:
          - accepted_values:
              arguments:
                values: ['high', 'low']
YAML

cat > remediation_changes.md <<'MD'
# Remediation changes - customer_ltv (lift-and-shift -> idiomatic)

| Anti-pattern (before) | Fix (after) |
|---|---|
| Monolith reading the raw seed directly, no staging | `stg_orders` staging model + `customer_ltv` mart wired via `ref()` |
| Data-quality `DELETE` in a `post_hook` | removed; the grain is enforced by `not_null`/`unique` tests |
| No tests or docs | unique/not_null on the grain, accepted_values on `ltv_segment`, model descriptions |

Results unchanged: same customers, `lifetime_value`, `order_count`, and `ltv_segment`.
MD

export DBT_PROFILES_DIR=/app/project
dbt build
