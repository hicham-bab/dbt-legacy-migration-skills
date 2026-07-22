# canary GUID (keep): HARBOR-TASK-CANARY a9c4d3e6-migrate-informatica-to-dbt
"""Verifier: build the agent's dbt project and check mart_fct_customer_orders matches legacy output.

Runs inside the container after the agent finishes. Success = the project builds AND
mart_fct_customer_orders equals expected_fct_customer_orders.csv row-for-row (the parity gate) —
the captured output of the legacy Informatica mapping (completed orders, aggregated per customer,
value_band = 'A' when lifetime_amount >= 200 else 'B'). The expected file lives with the verifier,
hidden from the agent.
"""
import csv
import os
import subprocess
from pathlib import Path

PROJECT = Path("/app/project")
EXPECTED = Path(__file__).parent / "expected_fct_customer_orders.csv"
MART = "mart_fct_customer_orders"


def _build():
    env = {**os.environ, "DBT_PROFILES_DIR": str(PROJECT)}
    for cmd in (["dbt", "deps"], ["dbt", "build"]):
        r = subprocess.run(cmd, cwd=PROJECT, env=env, capture_output=True, text=True)
        if cmd[1] == "build" and r.returncode != 0:
            raise AssertionError(f"dbt build failed:\n{r.stdout[-2000:]}\n{r.stderr[-1000:]}")


def _load_expected():
    with open(EXPECTED) as f:
        return {r["customer_id"]: r for r in csv.DictReader(f)}


def _query_mart():
    import duckdb
    con = duckdb.connect(str(PROJECT / "dev.duckdb"))
    tbls = con.execute(
        "select table_schema, table_name from information_schema.tables "
        f"where lower(table_name) = '{MART}'").fetchall()
    assert tbls, f"{MART} not found in the built warehouse"
    schema, name = tbls[0]
    rows = con.execute(
        f'select customer_id, lifetime_amount, order_count, value_band from "{schema}"."{name}"'
    ).fetchall()
    return {str(int(r[0])): {"customer_id": str(int(r[0])),
                             "lifetime_amount": f"{float(r[1]):.2f}",
                             "order_count": str(int(r[2])),
                             "value_band": str(r[3])} for r in rows}


def test_project_exists():
    assert (PROJECT / "dbt_project.yml").exists(), "no dbt_project.yml in /app/project"


def test_builds_and_matches_legacy_output():
    _build()
    expected = _load_expected()
    actual = _query_mart()
    assert set(actual) == set(expected), f"row keys differ: got {sorted(actual)} vs {sorted(expected)}"
    for cid, exp in expected.items():
        got = actual[cid]
        assert f"{float(got['lifetime_amount']):.2f}" == f"{float(exp['lifetime_amount']):.2f}", \
            f"customer {cid} lifetime_amount {got['lifetime_amount']} != {exp['lifetime_amount']}"
        assert got["order_count"] == exp["order_count"], \
            f"customer {cid} order_count {got['order_count']} != {exp['order_count']}"
        assert got["value_band"] == exp["value_band"], \
            f"customer {cid} value_band {got['value_band']} != {exp['value_band']}"
