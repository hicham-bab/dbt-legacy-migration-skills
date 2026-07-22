# canary GUID (keep): HARBOR-TASK-CANARY 7b2e9f14-migrate-talend-to-dbt
"""Verifier: build the agent's dbt project and check mart_customer_revenue matches the legacy output.

Runs inside the container after the agent finishes. Success = the project builds AND
mart_customer_revenue equals expected_customer_revenue.csv row-for-row (the parity gate) —
the captured output of the legacy Talend job (completed orders, joined to customers, aggregated
per customer). The expected file lives with the verifier, hidden from the agent.
"""
import csv
import os
import subprocess
from pathlib import Path

PROJECT = Path("/app/project")
EXPECTED = Path(__file__).parent / "expected_customer_revenue.csv"
MART = "mart_customer_revenue"


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
        f'select customer_id, customer_name, total_revenue, order_count from "{schema}"."{name}"'
    ).fetchall()
    return {str(int(r[0])): {"customer_id": str(int(r[0])), "customer_name": str(r[1]),
                             "total_revenue": f"{float(r[2]):.2f}",
                             "order_count": str(int(r[3]))} for r in rows}


def test_project_exists():
    assert (PROJECT / "dbt_project.yml").exists(), "no dbt_project.yml in /app/project"


def test_builds_and_matches_legacy_output():
    _build()
    expected = _load_expected()
    actual = _query_mart()
    assert set(actual) == set(expected), f"row keys differ: got {sorted(actual)} vs {sorted(expected)}"
    for cid, exp in expected.items():
        got = actual[cid]
        assert got["customer_name"] == exp["customer_name"], \
            f"customer {cid} name {got['customer_name']} != {exp['customer_name']}"
        assert f"{float(got['total_revenue']):.2f}" == f"{float(exp['total_revenue']):.2f}", \
            f"customer {cid} total_revenue {got['total_revenue']} != {exp['total_revenue']}"
        assert got["order_count"] == exp["order_count"], \
            f"customer {cid} order_count {got['order_count']} != {exp['order_count']}"
