# Evals — parser regression tests

Runs the deterministic inventory parsers against small, self-authored fixtures and asserts on
their output (component counts, coverage denominator, out-of-scope detection, SCD2/dynamic-SQL
flagging). Catches regressions in a parser or answer key automatically.

```bash
python3 evals/run_evals.py             # exits 0 if all checks pass, 1 otherwise
python3 evals/run_evals.py --write     # also regenerates RESULTS.md + results.json
```

## Published results

- **[RESULTS.md](RESULTS.md)** — the full per-check breakdown, grouped by source. Auto-generated
  and refreshed by CI on every push to `main` (see [`.github/workflows/evals.yml`](../.github/workflows/evals.yml)).
- **[results.json](results.json)** — machine-readable summary; backs the README eval badge via a
  shields.io endpoint.
- CI (GitHub Actions) runs this harness on every push and PR, publishes the breakdown to the run's
  job summary, uploads `results.json` as an artifact, and **fails the build on any regression** — so
  the eval numbers are always current and gated, not a stale claim.

- **Fixtures** (`evals/fixtures/`) are minimal and hand-authored — no user or third-party data.
  The parsers were *also* verified against real exports during development; these fixtures make the
  check self-contained and repeatable.
- **Stdlib only**, except the Matillion **DPC-YAML** case, which needs `pyyaml`
  (`pip install pyyaml`) and is skipped-with-a-note otherwise; the Matillion **METL-JSON** case
  always runs.

Parsers under test:
| Source | Script |
|--------|--------|
| Talend | `migrating-talend-to-dbt/scripts/inventory_talend.py` |
| Informatica | `migrating-informatica-to-dbt/scripts/inventory_informatica.py` |
| Matillion | `migrating-matillion-to-dbt/scripts/inventory_matillion.py` |
| Stored procedures | `migrating-stored-procedures-to-dbt/scripts/inventory_stored_proc.py` (heuristic scan) |
