# Evals — parser regression tests

Runs the deterministic inventory parsers against small, self-authored fixtures and asserts on
their output (component counts, coverage denominator, out-of-scope detection, SCD2/dynamic-SQL
flagging). Catches regressions in a parser or answer key automatically.

```bash
python3 evals/run_evals.py     # exits 0 if all checks pass, 1 otherwise
```

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
