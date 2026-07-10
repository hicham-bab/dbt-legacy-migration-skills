# Choosing dimension vs fact & declaring the grain

Use this to map a source entity (or a mapped legacy unit) to a dimension or a fact. The modeling
decision is yours; the SQL is plain dbt.

## Contents

- [Declare the grain first](#declare-the-grain-first)
- [Dimension or fact?](#dimension-or-fact)
- [Special dimension patterns](#special-dimension-patterns)
- [Special fact patterns](#special-fact-patterns)

## Declare the grain first

The **grain** is what one fact row represents — write it as "one row per _____". Everything depends
on it:
- The grain fixes the fact's **primary/grain key** (often a surrogate of the natural key columns).
- It fixes which **dimensions** the fact references (one FK per dimension at that grain).
- It fixes which **measures** are valid (a measure must be additive at the declared grain, or you
  mark it semi-/non-additive).

Never mix grains in one fact (e.g. order-header and order-line facts are two separate facts). If a
legacy mart mixed grains, split it.

## Dimension or fact?

| Source entity looks like… | Model as | Signals |
|---|---|---|
| A **thing / actor / reference** (customer, product, store, employee, date) with descriptive attributes | **Dimension** (`dim_`) | stable business key; attributes people filter/group by; changes slowly |
| A **business event / measurement** (order line, payment, shipment, daily balance) | **Fact** (`fct_`) | has a date + measures; high row count; references several dimensions |
| A **code / lookup** table (currency, country, status) | Small **dimension** (or seed) | few rows; used only for labels |
| A **relationship with no measures** (customer↔promotion eligibility) | **Factless fact** | captures that an event/coverage happened |

Rule of thumb: if you'd *group by* it or *filter on* it → dimension; if you'd *sum/count/average* it
over time → fact. A column can be both a measure (in the fact) and, bucketed, a dimension attribute.

## Special dimension patterns

- **Degenerate dimension** — a dimension-like attribute with no other attributes (order number,
  invoice number). Keep it **on the fact** as a plain column; don't build a one-column dim.
- **Role-playing dimension** — one physical dimension used in several roles (order date, ship date,
  due date all reference `dim_date`). Build `dim_date` once; the fact carries multiple date FKs
  (`order_date_key`, `ship_date_key`); expose views/aliases per role if the BI tool needs them.
- **Junk dimension** — a grab-bag of low-cardinality flags/indicators combined into one small dim to
  avoid many boolean columns on the fact.
- **Conformed dimension** — the same dimension shared by multiple facts/processes. Build once, reuse
  (see `dimensions-and-scd.md` → bus matrix).

## Special fact patterns

- **Transaction fact** — one row per event (the common case). Insert-only / incremental.
- **Periodic snapshot fact** — one row per entity per period (daily account balance). Grain = entity
  + period.
- **Accumulating snapshot fact** — one row per pipeline instance, updated as it moves through
  milestones (order → picked → shipped → delivered), with multiple date FKs and lag measures.
- **Factless fact** — event/coverage with no measures (student attendance, promotion eligibility);
  you count rows.

Record each fact's grain and its dimension list — that inventory drives the models and the
`relationships` tests. See `facts-and-performance.md` for materialization.
