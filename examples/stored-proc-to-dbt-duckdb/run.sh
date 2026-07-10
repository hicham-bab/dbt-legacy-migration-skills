#!/usr/bin/env bash
# Runs the stored-proc -> dbt migration example end-to-end on DuckDB (free, local, no warehouse).
# Requires dbt-duckdb (pip install dbt-duckdb). Uses DBT_PROFILES_DIR=. so no ~/.dbt setup needed.
set -euo pipefail
cd "$(dirname "$0")"
export DBT_PROFILES_DIR="$PWD"

dbt deps
# seeds (raw + captured legacy output) + models + data tests, incl. the parity gate.
dbt build
echo
echo "PASS: dbt build green — migrated mart matches the legacy output row-for-row"
echo "      (parity gate: tests/assert_customer_ltv_parity.sql returned 0 rows)."
