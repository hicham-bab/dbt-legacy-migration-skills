# Harbor aggregate scorecard

> Oracle-solution smoke test across all migration tasks (`python3 harbor/_scorer/run_all.py`). Full agent evals run via `harbor run`.

| Task | Weighted | Parity | Coverage | Structural | Judge | Reward |
|---|---|---|---|---|---|---|
| migrate-coalesce-to-dbt | 100% | 100% | 100% | 100% | skip | 1 |
| migrate-informatica-to-dbt | 100% | 100% | 100% | 100% | skip | 1 |
| migrate-matillion-to-dbt | 100% | 100% | 100% | 100% | skip | 1 |
| migrate-stored-proc-to-dbt | 100% | 100% | 100% | 100% | skip | 1 |
| migrate-talend-to-dbt | 100% | 100% | 100% | 100% | skip | 1 |
