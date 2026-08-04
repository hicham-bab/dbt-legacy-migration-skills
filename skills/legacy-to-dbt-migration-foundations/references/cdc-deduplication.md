# CDC deduplication: a first-class migration pattern (Step 3)

A common blocker when migrating from a legacy warehouse (Redshift, Oracle, Teradata) to a CDC-sourced
platform (Databricks / Snowflake fed by Fivetran, Airbyte, DMS, Guidewire CDA, etc.): the **legacy
system presented pre-deduplicated views**, but the migrated dbt models join **raw CDC tables that
expose the full revision history** - many rows per business key, one per `commit_timestamp` (or
`_fivetran_synced`, `dms_seq`, ...). Join those raw tables directly and **every join fans out**. This
is one of the most frequent lift-and-shift regressions, and it shows up as a **precision** failure in
the Step 5 dual-metric check (extra rows), not a recall failure.

## The pattern: dedup at the source, inline, before joining

Wrap every raw CDC source in a `QUALIFY` subquery that keeps only the latest revision per key:

```sql
-- Instead of joining the raw CDC table directly:
inner join {{ source('sor', 'cc_claim') }} claim on claim.id = base.claim_id

-- dedup to the current revision first:
inner join (
    select id, relevant_col_1, relevant_col_2
    from {{ source('sor', 'cc_claim') }}
    qualify row_number() over (partition by id order by commit_timestamp desc) = 1
) claim on claim.id = base.claim_id
```

Prefer doing this once in the **staging layer** (one deduped `stg_` model per CDC source), so marts
join already-current rows and the dedup logic lives in one place.

## Traps to document

- **`SELECT DISTINCT` does NOT collapse CDC duplicates.** If any column changed between revisions
  (which is the whole point of CDC), the rows are distinct and `DISTINCT` keeps them all. This is the
  single most common mistake porting a Redshift/Oracle view. Use `QUALIFY row_number()`, not `DISTINCT`.
- **Reference / TypeList tables carry CDC history too.** Lookups like Guidewire `cctl_*` typecode
  tables are also CDC-sourced and need the same dedup, easy to miss because they "look static".
- **Dedup on the right key.** For a table with a business-natural key (not just a surrogate `id`),
  `QUALIFY` on the **business key**, not `id`, or you keep stale revisions of an active record.
- **Deterministic tiebreak.** If two revisions share the max `commit_timestamp`, add a deterministic
  secondary sort (e.g. `order by commit_timestamp desc, _seq desc`) so the chosen row is stable across
  runs (`row_number()` ties are non-deterministic - see
  [warehouse-conformance.md](warehouse-conformance.md)).

## Where this fits

This is a Step 3 (translate) concern that is **cross-source**: any migration whose target platform is
fed by CDC needs it, regardless of the legacy tool. Flag it during Step 1 inventory whenever the
target sources are raw CDC landing tables, and verify it worked with the precision metric in Step 5
([data-validation.md](data-validation.md)).
