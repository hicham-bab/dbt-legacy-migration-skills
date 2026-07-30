#!/usr/bin/env python3
"""Idiomatic-dbt anti-pattern linter: the runtime "migration quality bar".

Catches the lift-and-shift patterns that turn a migration into technical debt, the exact failure
mode behind badly-migrated estates (hook-laden, monolithic, legacy control-flow copied over). Runs
on a dbt project directory using source-file heuristics (so it works before a build); if a compiled
`target/manifest.json` is present it also scores test/doc coverage (same signal as the harbor
scorecard's structural dimension).

Checks:
  - hooks         (warn)  pre_hook / post_hook usage; migrated logic usually belongs in a model,
                          test, macro, or snapshot, not a hook.
  - hardcoded_ref (error) `from`/`join <db>.<schema>.<table>` instead of ref()/source().
  - control_flow  (error) cursors/loops/EXECUTE IMMEDIATE/CALL copied from the legacy tool.
  - monolith      (warn)  a single model over MONOLITH_LINES lines.
  - no_layering   (warn)  marts exist but there are no staging models.
  - low_tests     (warn)  (manifest only) < TEST_COVERAGE_MIN of models have a test.

Usage: python3 scripts/lint_idiomatic.py [project-dir] [--json] [--strict]
Exit: non-zero if any error-severity finding (or any finding with --strict). This is the gate.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MONOLITH_LINES = 200
TEST_COVERAGE_MIN = 0.5

JINJA = re.compile(r"\{\{.*?\}\}", re.S)
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"--[^\n]*")
HARDCODED = re.compile(r"\b(from|join)\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)", re.I)
HOOK = re.compile(r"(?:pre|post)[_-]hook\s*[:=]", re.I)  # config assignment, not prose mentions
CONTROL = re.compile(r"\b(cursor|while|loop|fetch|execute\s+immediate|\bexec\b|call\s+\w+\s*\()\b", re.I)


def _strip(sql: str) -> str:
    """Remove jinja and comments so heuristics don't match ref() args or commented legacy code."""
    return LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", JINJA.sub(" ", sql)))


def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def lint(project: Path) -> dict:
    findings: list[dict] = []
    models = sorted((project / "models").rglob("*.sql")) if (project / "models").is_dir() else []
    yml = [p for pat in ("**/*.yml", "**/*.yaml") for p in (project / "models").rglob(pat)] \
        if (project / "models").is_dir() else []
    project_yml = project / "dbt_project.yml"

    def add(check, severity, path, detail):
        findings.append({"check": check, "severity": severity, "file": _rel(path, project), "detail": detail})

    # hooks: in model SQL config(), schema yml, and dbt_project.yml
    for p in models + yml + ([project_yml] if project_yml.exists() else []):
        text = p.read_text(errors="ignore")
        if HOOK.search(text):
            add("hooks", "warn", p,
                "pre/post-hook present; check the logic isn't better expressed as a model, test, macro, or snapshot")

    staging = [m for m in models if "staging" in _rel(m, project) or Path(m).name.startswith("stg_")]
    marts = [m for m in models if "mart" in _rel(m, project) or Path(m).name.startswith(("fct_", "dim_", "mart_"))]

    for m in models:
        body = _strip(m.read_text(errors="ignore"))
        for kw, target in HARDCODED.findall(body):
            add("hardcoded_ref", "error", m, f"{kw} {target}: use ref()/source(), not a hardcoded relation")
        if CONTROL.search(body):
            add("control_flow", "error", m, "legacy control-flow (cursor/loop/EXECUTE IMMEDIATE/CALL) should become set-based SQL")
        n = len(m.read_text(errors="ignore").splitlines())
        if n > MONOLITH_LINES:
            add("monolith", "warn", m, f"{n} lines: consider decomposing into staging/intermediate models")

    if marts and not staging:
        add("no_layering", "warn", project, "marts exist but no staging models found; a flat lift-and-shift skips source-conformed staging")

    # optional: test coverage from a compiled manifest (same signal as the harbor structural dimension)
    manifest = project / "target" / "manifest.json"
    if manifest.exists():
        man = json.loads(manifest.read_text())
        mnodes = [n for n in man.get("nodes", {}).values() if n.get("resource_type") == "model"]
        tested = {d for n in man.get("nodes", {}).values() if n.get("resource_type") == "test"
                  for d in n.get("depends_on", {}).get("nodes", [])}
        if mnodes:
            cov = sum(1 for m in mnodes if m["unique_id"] in tested) / len(mnodes)
            if cov < TEST_COVERAGE_MIN:
                add("low_tests", "warn", project, f"only {cov*100:.0f}% of models have a test (target >= {TEST_COVERAGE_MIN*100:.0f}%)")

    errors = sum(1 for f in findings if f["severity"] == "error")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    return {"project": str(project), "findings": findings,
            "summary": {"errors": errors, "warnings": warns, "models": len(models), "staging": len(staging)}}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    project = Path(args[0]) if args else Path(".")
    strict = "--strict" in argv
    report = lint(project)
    if "--json" in argv:
        print(json.dumps(report, indent=2))
    else:
        s = report["summary"]
        print(f"Idiomatic lint: {s['errors']} error(s), {s['warnings']} warning(s) "
              f"across {s['models']} models ({s['staging']} staging)\n")
        for f in report["findings"]:
            mark = "ERROR" if f["severity"] == "error" else "warn "
            print(f"  [{mark}] {f['check']}: {f['file']} - {f['detail']}")
        if not report["findings"]:
            print("  clean: no anti-patterns detected.")
    fail = report["summary"]["errors"] > 0 or (strict and report["summary"]["warnings"] > 0)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
