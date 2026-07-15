#!/usr/bin/env python3
"""Hard decision gate for a legacy->dbt migration (stdlib only).

The migration MUST NOT build any models until the migrator has chosen:
  1. target_architecture   (kimball | datavault | star | layered)
  2. data_warehouse        (snowflake | databricks | bigquery | redshift)   -> drives SQL dialect
  3. packages_mode         (external_hub | self_contained_macros)

This script is the enforcement: the skill runs it FIRST. If the decisions file is
missing or incomplete it EXITS NON-ZERO and prints the exact questions (with a detected
recommendation). The agent must then ask the migrator, write their answers to the file,
and re-run until this passes. Only on exit 0 may model-building begin.

Usage:
    python3 preflight_decisions.py [--file migration_decisions.yml] [--profiles ~/.dbt/profiles.yml]

Decisions file format (flat `key: value`, e.g. migration_decisions.yml):
    target_architecture: kimball
    data_warehouse: snowflake
    packages_mode: external_hub
    landing_spot: /path/to/new/dbt/project      # optional but recommended
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

REQUIRED = {
    "target_architecture": {"kimball", "datavault", "star", "layered"},
    "data_warehouse": {"snowflake", "databricks", "bigquery", "redshift"},
    "packages_mode": {"external_hub", "self_contained_macros"},
}
QUESTIONS = {
    "target_architecture":
        "Which target architecture? kimball | datavault | star | layered "
        "(Data Vault = auditable hubs/links/sats; Kimball = conformed dims+facts; "
        "star = one lightweight star; layered = faithful port).",
    "data_warehouse":
        "Which data warehouse are we targeting? snowflake | databricks | bigquery | redshift "
        "(this sets the SQL dialect the generated dbt models use).",
    "packages_mode":
        "Use external dbt packages (from hub.getdbt.com) or self-contained hand-made macros? "
        "external_hub | self_contained_macros.",
}


def read_decisions(path: Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip("'\"")
            # normalize only the enum decisions; keep free-text (paths) verbatim
            out[key] = val.lower() if key in REQUIRED else val
    return out


def detect_warehouse(profiles: Path) -> str | None:
    """Best-effort read of a `type:` from profiles.yml to recommend the warehouse."""
    if not profiles.exists():
        return None
    for line in profiles.read_text().splitlines():
        m = re.match(r"\s*type:\s*([A-Za-z0-9_]+)", line)
        if m and m.group(1).lower() in REQUIRED["data_warehouse"]:
            return m.group(1).lower()
    return None


def main(argv):
    fpath = Path("migration_decisions.yml")
    ppath = Path(os.path.expanduser("~/.dbt/profiles.yml"))
    i = 0
    while i < len(argv):
        if argv[i] == "--file":
            fpath = Path(argv[i + 1]); i += 2
        elif argv[i] == "--profiles":
            ppath = Path(os.path.expanduser(argv[i + 1])); i += 2
        else:
            i += 1

    decisions = read_decisions(fpath)
    missing, invalid = [], []
    for key, allowed in REQUIRED.items():
        val = decisions.get(key)
        if not val:
            missing.append(key)
        elif val not in allowed:
            invalid.append((key, val, allowed))

    if missing or invalid:
        rec_wh = detect_warehouse(ppath)
        print("=" * 70)
        print("STOP — migration decisions required before building any models.")
        print("=" * 70)
        print(f"Decisions file: {fpath}  (create/complete it, then re-run this script)\n")
        print("Ask the migrator these questions and record their answers "
              "(recommend, but they decide):\n")
        for key in REQUIRED:
            if key in missing or any(k == key for k, _, _ in invalid):
                q = QUESTIONS[key]
                print(f"  [{key}] {q}")
                if key == "data_warehouse" and rec_wh:
                    print(f"        (detected in profiles.yml: '{rec_wh}' — recommend, but confirm)")
                print()
        for key, val, allowed in invalid:
            print(f"  ! '{key}' = '{val}' is not one of {sorted(allowed)}")
        print("Write answers to the file as `key: value` lines, then re-run. "
              "Do NOT create models until this exits 0.")
        return 1

    print("Migration decisions recorded — OK to proceed:")
    for key in REQUIRED:
        print(f"  {key}: {decisions[key]}")
    if decisions.get("landing_spot"):
        print(f"  landing_spot: {decisions['landing_spot']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
