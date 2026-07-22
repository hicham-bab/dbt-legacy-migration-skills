# canary GUID (keep): HARBOR-TASK-CANARY d3f1c0a2-migrate-stored-proc-to-dbt
"""Verifier: build the agent's dbt project and check mart_customer_ltv matches the legacy output.

Runs inside the container after the agent finishes. Success = the project builds AND
mart_customer_ltv equals expected/legacy_customer_ltv.csv row-for-row (the parity gate).
"""
import csv
import os
import subprocess
from pathlib import Path

PROJECT = Path("/app/project")
EXPECTED = Path(__file__).parent / "legacy_customer_ltv.csv"


def _build():
    env = {**os.environ, "DBT_PROFILES_DIR": str(PROJECT)}
    for cmd in (["dbt", "deps"], ["dbt", "build"]):
        r = subprocess.run(cmd, cwd=PROJECT, env=env, capture_output=True, text=True)
        # deps may be a no-op/no packages.yml; only fail hard on build
        if cmd[1] == "build" and r.returncode != 0:
            raise AssertionError(f"dbt build failed:\n{r.stdout[-2000:]}\n{r.stderr[-1000:]}")


def _load_expected():
    with open(EXPECTED) as f:
        return {r["customer_id"]: r for r in csv.DictReader(f)}


def _query_mart():
    import duckdb
    con = duckdb.connect(str(PROJECT / "dev.duckdb"))
    # find the mart regardless of schema
    tbls = con.execute(
        "select table_schema, table_name from information_schema.tables "
        "where lower(table_name) = 'mart_customer_ltv'").fetchall()
    assert tbls, "mart_customer_ltv not found in the built warehouse"
    schema, name = tbls[0]
    rows = con.execute(
        f'select customer_id, lifetime_value, order_count, ltv_segment from "{schema}"."{name}"'
    ).fetchall()
    return {str(int(r[0])): {"customer_id": str(int(r[0])),
                             "lifetime_value": f"{float(r[1]):.2f}",
                             "order_count": str(int(r[2])),
                             "ltv_segment": str(r[3])} for r in rows}


def test_project_exists():
    assert (PROJECT / "dbt_project.yml").exists(), "no dbt_project.yml in /app/project"


def test_builds_and_matches_legacy_output():
    _build()
    expected = _load_expected()
    actual = _query_mart()
    assert set(actual) == set(expected), f"row keys differ: got {sorted(actual)} vs {sorted(expected)}"
    for cid, exp in expected.items():
        got = actual[cid]
        assert f"{float(got['lifetime_value']):.2f}" == f"{float(exp['lifetime_value']):.2f}", \
            f"customer {cid} lifetime_value {got['lifetime_value']} != {exp['lifetime_value']}"
        assert got["order_count"] == exp["order_count"], \
            f"customer {cid} order_count {got['order_count']} != {exp['order_count']}"
        assert got["ltv_segment"] == exp["ltv_segment"], \
            f"customer {cid} ltv_segment {got['ltv_segment']} != {exp['ltv_segment']}"
