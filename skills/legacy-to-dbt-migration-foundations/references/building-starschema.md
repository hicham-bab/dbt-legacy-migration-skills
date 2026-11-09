# Building a star schema (Step 3, modeling approach = Star)

One star for one subject area: a single `fct_` + its `dim_`s, minimal ceremony. Same building blocks
as [building-kimball.md](building-kimball.md) without the conformed-dimension / bus-matrix program —
use this for a focused mart or a quick BI-friendly migration. The legacy→dim/fact mapping is in
[target-modeling.md](target-modeling.md#star-schema).

## Approach

1. **Declare the fact grain** ("one row per …"), same discipline as Kimball.
2. **Build the dimensions the fact needs** — usually **Type 1** (overwrite) `dim_` tables. Add
   Type-2 history only for a dimension the business actually tracks over time; pick the mechanism
   (snapshot / incremental-merge / hybrid) via [scd-history-strategies.md](scd-history-strategies.md),
   default hybrid (see building-kimball.md).
3. **Build the fact** at the grain, referencing the dims. Surrogate keys are **optional** for a
   self-contained star (natural keys acceptable as FKs), but prefer them if the star may grow into a
   conformed model.
4. Layer: `stg_` (view) → optional `int_` → `dim_`/`fct_` (dim=table; fact=table, or `incremental`
   if large).

```sql
-- models/marts/dim_customer.sql (table) — Type 1
select {{ dbt_utils.generate_surrogate_key(['customer_id']) }} as customer_key,
       customer_id, customer_name, segment, region
from {{ ref('stg_customers') }}
```
```sql
-- models/marts/fct_sales.sql — grain: one row per sales line
with sales_lines as (
    select * from {{ ref('stg_sales_lines') }}
),
keyed as (
    select
        {{ dbt_utils.generate_surrogate_key(['s.sale_id','s.line_number']) }} as sales_line_key,
        c.customer_key,
        p.product_key,
        {{ dbt_utils.generate_surrogate_key(['s.sale_date']) }} as date_key,
        s.sale_id,                                             -- degenerate dimension
        cast(s.quantity as integer)          as quantity,
        cast(s.amount as decimal(18,2))      as amount
    from sales_lines s
    left join {{ ref('dim_customer') }} c on s.customer_id = c.customer_id
    left join {{ ref('dim_product') }}  p on s.product_id  = p.product_id
),
final as (select * from keyed)
select * from final
```

Note the CTE structure: it is not decoration. It satisfies the structural rule in
[dbt-best-practices.md](dbt-best-practices.md) (wrap logic in CTEs, name the final CTE `final`),
and it is what makes a parity failure debuggable — you can select from any intermediate CTE to
find the step where row counts diverge.

**Type-2 dimension warning.** The dimensions above are Type 1, so a join on the natural key is
safe. Against a **Type-2** dimension the same join **fans out** — one fact row multiplies by the
number of historical versions. Join on the surrogate key resolved at the event time, using a
point-in-time predicate (`and s.sale_date >= c.valid_from and s.sale_date < c.valid_to`).
See [building-kimball.md](building-kimball.md).

**Snowflake-schema variant:** normalizing a dimension (dim → sub-dim) trades a wider dim for extra
joins. Prefer **denormalized** star dims for query performance; snowflake only a large, reused
sub-dim, and note the extra join.

**Tests/docs/contracts** (via the `arguments:` spec — [dbt-best-practices.md](dbt-best-practices.md)):
`unique`+`not_null` on each dim key and the fact grain key; `relationships` from each fact FK to its
dim; `accepted_values` on low-cardinality columns; docs state the grain; `contract: enforced` on
anything others consume.

**Performance:** fact = `table` when small, `incremental` + partition/cluster (date + main FK) once
large; dims = clustered tables; keep the fact narrow. A single star is a small, cheap DAG. See
[cloud-detection-and-materializations.md](cloud-detection-and-materializations.md).

**Common mistakes:** reinventing conformed-dimension machinery for one star (keep it light; use
Kimball only when facts must share dims); Type-2 where none is needed (use Type-1 overwrite);
snowflaking every dimension; null fact FKs (left-join + unknown member).
