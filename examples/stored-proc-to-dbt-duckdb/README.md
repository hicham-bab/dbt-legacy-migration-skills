# Runnable example — stored procedure → dbt, proven on DuckDB

A **complete, self-contained** migration you can run in ~10 seconds with no warehouse and no
credentials. It demonstrates what the `migrating-stored-procedures-to-dbt` skill produces and — the
important part — **proves the migrated model matches the legacy output** with a real `dbt build`.

## What's here

| Piece | Role |
|-------|------|
| `legacy/sp_customer_ltv.sql` | the legacy stored procedure (reference input) |
| `seeds/raw_customers.csv`, `seeds/raw_orders.csv` | the raw source data |
| `seeds/legacy_customer_ltv.csv` | the legacy procedure's **captured output** (the "prod" table to match) |
| `models/staging/*`, `models/marts/mart_customer_ltv.sql` | the migrated dbt models (ref()-based, decomposed from the proc) |
| `models/marts/_marts.yml` | tests + docs (`unique`/`not_null`/`accepted_values` via the `arguments:` spec) |
| `tests/assert_customer_ltv_parity.sql` | **the parity gate** — a singular test that fails the build if the mart ≠ legacy output |
| `analyses/validate_customer_ltv.sql` | the same parity via the recommended **audit_helper** classify macro |

## Run it

```bash
pip install dbt-duckdb           # dbt Core + DuckDB adapter (free, local)
cd examples/stored-proc-to-dbt-duckdb
DBT_PROFILES_DIR=. dbt deps
DBT_PROFILES_DIR=. dbt build     # seeds + models + tests, incl. the parity gate
# or: ./run.sh
```

A green `dbt build` means: the migrated `mart_customer_ltv` reproduces the legacy procedure's output
**row-for-row** (the parity gate returned 0 mismatches), and the data tests pass.

## Prove the gate is real

Break the logic and watch the build fail:

```bash
sed -i '' 's/>= 150/>= 250/' models/marts/mart_customer_ltv.sql   # change a segmentation threshold
DBT_PROFILES_DIR=. dbt build -s mart_customer_ltv assert_customer_ltv_parity   # -> FAIL (mismatch)
git checkout -- models/marts/mart_customer_ltv.sql                # restore
```

## Notes

- Runs on **dbt Core + DuckDB** so it's free and offline. The skills themselves target **dbt Fusion
  + a cloud warehouse** (Snowflake/BigQuery/Databricks/Redshift); this example is a portable proof of
  the *pattern* and the *parity method*, not the Fusion path.
- The parity gate here uses a plain full-outer-join singular test (adapter-safe everywhere);
  `analyses/validate_customer_ltv.sql` shows the same check via the `audit_helper` package, which is
  what the skill uses when external packages are allowed.
- This example is exercised by CI on every push/PR (`.github/workflows/ci.yml`).
