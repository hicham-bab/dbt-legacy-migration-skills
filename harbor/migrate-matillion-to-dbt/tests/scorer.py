"""Shared scorecard for the harbor end-to-end migration evals.

One migration produces one dbt project; this module scores it on five dimensions and writes a
weighted scorecard. It is the single source of truth - each task's `tests/scorer.py` is a copy
kept in sync by `harbor/_scorer/sync.sh` (drift is caught by `harbor/_scorer/check_sync.py`,
which the parser-tier CI runs).

Dimensions (deterministic first, judge last):
  1. build       - `dbt deps` + `dbt build` succeed. Hard gate: if it fails, the data-dependent
                   dimensions score 0 (nothing to query).
  2. parity      - every declared mart matches its held-out expected CSV row-for-row. The
                   correctness gate. Numeric columns compared with a small tolerance.
  3. coverage    - produced models vs. the skill's own inventory `coverage_denominator`
                   (a directional proxy for "did we migrate the whole workload").
  4. structural  - idiomatic-dbt signals read from target/manifest.json: test coverage,
                   documentation, and staging→marts layering.
  5. judge       - LLM-as-judge over what the deterministic checks miss (SCD correctness,
                   decomposition, docs/migration_changes completeness, test meaningfulness).
                   Runs via the Anthropic API (ANTHROPIC_API_KEY); recorded but never gates the
                   reward, and skipped-with-note when no key/SDK is present.

The **reward** (Harbor's 1/0) is the correctness gate: build AND parity==1.0 AND coverage>=threshold.
The scorecard captures the fuller quality picture regardless.
"""
from __future__ import annotations

import glob
import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- small helpers --------------------------------------------------------


def _num(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


@dataclass
class Dimension:
    name: str
    score: float            # 0..1
    weight: float
    detail: str = ""
    ran: bool = True        # False => skipped (e.g. judge with no API key); excluded from the total


@dataclass
class Scorecard:
    task: str
    project: Path
    dimensions: list[Dimension] = field(default_factory=list)

    def add(self, d: Dimension) -> None:
        self.dimensions.append(d)

    @property
    def total(self) -> float:
        active = [d for d in self.dimensions if d.ran]
        w = sum(d.weight for d in active)
        return sum(d.score * d.weight for d in active) / w if w else 0.0

    def get(self, name: str) -> Dimension | None:
        return next((d for d in self.dimensions if d.name == name), None)

    def as_dict(self) -> dict:
        return {
            "task": self.task,
            "total": round(self.total, 4),
            "dimensions": [
                {"name": d.name, "score": round(d.score, 4), "weight": d.weight,
                 "ran": d.ran, "detail": d.detail}
                for d in self.dimensions
            ],
        }

    def to_markdown(self) -> str:
        lines = [f"# Scorecard - {self.task}", "",
                 f"**Weighted score: {self.total*100:.1f}%**", "",
                 "| Dimension | Score | Weight | Notes |", "|---|---|---|---|"]
        for d in self.dimensions:
            sc = "skipped" if not d.ran else f"{d.score*100:.0f}%"
            lines.append(f"| {d.name} | {sc} | {d.weight:g} | {d.detail} |")
        lines.append("")
        return "\n".join(lines)

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "scorecard.json").write_text(json.dumps(self.as_dict(), indent=2) + "\n")
        (out_dir / "SCORECARD.md").write_text(self.to_markdown())


# --- dimension 1: build ---------------------------------------------------


def run_build(project: Path) -> tuple[bool, str]:
    """`dbt deps` (best effort) then `dbt build`. Returns (ok, tail-of-log)."""
    env = {**os.environ, "DBT_PROFILES_DIR": str(project)}
    log = ""
    subprocess.run(["dbt", "deps"], cwd=project, env=env, capture_output=True, text=True)
    r = subprocess.run(["dbt", "build"], cwd=project, env=env, capture_output=True, text=True)
    log = (r.stdout or "")[-2500:] + (r.stderr or "")[-800:]
    return r.returncode == 0, log


# --- dimension 2: parity --------------------------------------------------


def _duckdb_path(project: Path) -> Path:
    # profiles.yml uses `path: dev.duckdb` relative to the project
    p = project / "dev.duckdb"
    return p if p.exists() else next(project.glob("*.duckdb"), p)


def _query_mart(project: Path, mart: str, cols: list[str]) -> list[dict]:
    import duckdb
    con = duckdb.connect(str(_duckdb_path(project)), read_only=True)
    found = con.execute(
        "select table_schema, table_name from information_schema.tables "
        "where lower(table_name) = ?", [mart.lower()]).fetchall()
    if not found:
        con.close()
        raise AssertionError(f"mart '{mart}' not found in the built warehouse")
    schema, name = found[0]
    collist = ", ".join(f'"{c}"' for c in cols)
    rows = con.execute(f'select {collist} from "{schema}"."{name}"').fetchall()
    con.close()
    return [dict(zip(cols, r)) for r in rows]


def score_parity(project: Path, marts: list[dict], tol: float = 0.01) -> Dimension:
    """Each mart spec: {name, key_cols, compare_cols, expected_csv, numeric_cols?}."""
    import csv
    weight = 0.0
    per_mart, matched = [], 0.0
    for m in marts:
        weight += 1
        cols = list(dict.fromkeys(m["key_cols"] + m["compare_cols"]))
        numeric = set(m.get("numeric_cols", []))
        try:
            actual = _query_mart(project, m["name"], cols)
        except Exception as e:
            per_mart.append(f"{m['name']}: {e}")
            continue
        with open(m["expected_csv"]) as f:
            expected = list(csv.DictReader(f))

        def key(row):
            return tuple(str(_num(row[k]) if _num(row[k]) is not None else row[k]) for k in m["key_cols"])

        exp_by = {key(r): r for r in expected}
        act_by = {key(r): r for r in actual}
        if set(exp_by) != set(act_by):
            per_mart.append(f"{m['name']}: row keys differ "
                            f"(exp {len(exp_by)} / got {len(act_by)})")
            continue
        bad = 0
        for k, er in exp_by.items():
            ar = act_by[k]
            for c in m["compare_cols"]:
                a, e = ar[c], er[c]
                if c in numeric:
                    na, ne = _num(a), _num(e)
                    if na is None or ne is None or not math.isclose(na, ne, abs_tol=tol):
                        bad += 1
                elif str(a).strip() != str(e).strip():
                    bad += 1
        if bad == 0:
            matched += 1
            per_mart.append(f"{m['name']}: ✓ {len(exp_by)} rows")
        else:
            per_mart.append(f"{m['name']}: {bad} cell mismatch(es)")
    return Dimension("parity", matched / weight if weight else 0.0, weight=3.0,
                     detail="; ".join(per_mart))


# --- dimension 3: coverage ------------------------------------------------


def _manifest(project: Path) -> dict:
    mf = project / "target" / "manifest.json"
    return json.loads(mf.read_text()) if mf.exists() else {}


def _models(project: Path) -> list[dict]:
    man = _manifest(project)
    return [n for n in man.get("nodes", {}).values() if n.get("resource_type") == "model"]


def score_coverage(project: Path, spec: dict) -> Dimension:
    """Two modes, in preference order:

    1. `expected_models` in the spec - coverage = fraction of those model names present in the
       manifest. Deterministic and fair: an ETL component often collapses into fewer dbt models,
       so a raw models/units ratio under-counts. This asks "are the required models all there".
    2. else the inventory proxy - min(1, produced_models / inventory.coverage_denominator).
    """
    model_names = {m["name"] for m in _models(project)}
    n_models = len(model_names)

    expected = spec.get("expected_models")
    if expected:
        present = [m for m in expected if m in model_names]
        missing = [m for m in expected if m not in model_names]
        ratio = len(present) / len(expected)
        detail = f"{len(present)}/{len(expected)} required models present"
        if missing:
            detail += f" (missing: {', '.join(missing)})"
        return Dimension("coverage", ratio, weight=1.5, detail=detail)

    inventory = spec.get("inventory")
    if not inventory:
        return Dimension("coverage", 1.0 if n_models else 0.0, weight=1.5,
                         detail=f"{n_models} models (no inventory declared)")
    skills_dir = os.environ.get("HARBOR_SKILLS_DIR", "/skills")
    script = inventory["script"]
    cand = [script, str(Path(skills_dir) / script),
            *glob.glob(str(Path(skills_dir) / "**" / Path(script).name), recursive=True)]
    resolved = next((c for c in cand if Path(c).exists()), None)
    if not resolved:
        return Dimension("coverage", 0.0, weight=1.5, detail=f"inventory script not found: {script}")
    try:
        out = subprocess.run(["python3", resolved, inventory["input"], "--json"],
                             capture_output=True, text=True)
        inv = json.loads(out.stdout)
        denom = inv.get("summary", {}).get(inventory.get("denom_key", "coverage_denominator"))
        if not denom:
            # stored-proc parser has no summary; fall back to step_count_denominator on proc 0
            denom = inv.get("procedures", [{}])[0].get("step_count_denominator")
    except Exception as e:
        return Dimension("coverage", 0.0, weight=1.5, detail=f"inventory failed: {e!r}")
    if not denom:
        return Dimension("coverage", 1.0 if n_models else 0.0, weight=1.5,
                         detail=f"{n_models} models (no denominator)")
    ratio = min(1.0, n_models / denom)
    return Dimension("coverage", ratio, weight=1.5,
                     detail=f"{n_models} models / {denom} inventoried units = {ratio*100:.0f}%")


# --- dimension 4: structural (manifest-based, idiomatic-dbt signals) -------


def score_structural(project: Path) -> Dimension:
    models = _models(project)
    if not models:
        return Dimension("structural", 0.0, weight=1.0, detail="no models in manifest")
    n = len(models)
    documented = sum(1 for m in models if (m.get("description") or "").strip()) / n
    man = _manifest(project)
    tested = {dep for node in man.get("nodes", {}).values()
              if node.get("resource_type") == "test"
              for dep in node.get("depends_on", {}).get("nodes", [])}
    test_cov = sum(1 for m in models if m["unique_id"] in tested) / n
    paths = " ".join(m.get("path", "") for m in models)
    layering = 1.0 if ("staging" in paths and ("mart" in paths or "intermediate" in paths)) else 0.5
    score = round((documented + test_cov + layering) / 3, 4)
    return Dimension("structural", score, weight=1.0,
                     detail=f"tests {test_cov*100:.0f}% · docs {documented*100:.0f}% · "
                            f"layering {'yes' if layering == 1 else 'partial'}")


# --- dimension 5: LLM-as-judge --------------------------------------------
#
# Two backends. The default is the dbt **Wizard** via **dbt-managed inference** (no raw API key):
# `dbt-wizard exec` runs non-interactively using the OAuth credentials baked into ~/.dbt (see the
# task Dockerfiles + harbor/_scorer/stage_wizard_auth.sh). The Anthropic SDK is a fallback for when
# a raw key is preferred. Selection via HARBOR_JUDGE_BACKEND = auto | wizard | anthropic | off.

JUDGE_MODEL = os.environ.get("HARBOR_JUDGE_MODEL", "claude-sonnet-5")
WIZARD_CMD = os.environ.get("HARBOR_WIZARD_CMD", "dbt-wizard")


def _judge_backend() -> str:
    """Resolve which judge backend to use given env + what's installed."""
    choice = os.environ.get("HARBOR_JUDGE_BACKEND", "auto").lower()
    if choice != "auto":
        return choice
    if shutil.which(WIZARD_CMD):
        return "wizard"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "off"


def _judge_prompt(project: Path, legacy_text: str, rubric: list[dict]) -> str:
    dims_spec = "\n".join(f"- {d['name']}: {d['description']}" for d in rubric)
    return (
        "You are a strict senior analytics engineer grading a legacy→dbt migration. Score ONLY on "
        "the rubric below. Ignore length and formatting; judge substance.\n\n"
        f"## Legacy source artifact\n```\n{legacy_text[:12000]}\n```\n\n"
        f"## Produced dbt project\n```\n{_gather_project_text(project)}\n```\n\n"
        f"## Rubric (score each 0.0-1.0)\n{dims_spec}\n\n"
        "Return ONLY minified JSON: {\"scores\": {\"<name>\": {\"score\": <0-1>, \"why\": \"<short>\"}}}."
    )


def _extract_scores(text: str) -> dict:
    raw = text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)["scores"]


def _gather_project_text(project: Path, limit: int = 24000) -> str:
    parts = []
    for pat in ("models/**/*.sql", "models/**/*.yml", "models/**/*.yaml",
                "migration_changes.md", "snapshots/**/*.sql"):
        for f in sorted(project.glob(pat)):
            parts.append(f"\n--- {f.relative_to(project)} ---\n{f.read_text()}")
    text = "".join(parts)
    return text[:limit]


def _judge_wizard(prompt: str) -> dict:
    """Grade via the dbt Wizard non-interactively (dbt-managed inference; no raw API key)."""
    env = {**os.environ, "WIZARD_INTERNAL": os.environ.get("WIZARD_INTERNAL", "1"),
           "DO_NOT_TRACK": os.environ.get("DO_NOT_TRACK", "1")}
    r = subprocess.run([WIZARD_CMD, "exec", prompt], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"{WIZARD_CMD} exec failed: {r.stderr[-400:]}")
    return _extract_scores(r.stdout)


def _judge_anthropic(prompt: str) -> dict:
    import anthropic
    msg = anthropic.Anthropic().messages.create(
        model=JUDGE_MODEL, max_tokens=1500, messages=[{"role": "user", "content": prompt}])
    return _extract_scores(msg.content[0].text)


def judge_raw(project: Path, legacy_text: str, rubric: list[dict]) -> dict:
    """Call the LLM judge via the resolved backend. Returns {"<dim>": {"score", "why"}} or raises.

    Bias controls: single numeric score per named dimension (no A/B ordering), explicit rubric,
    JSON-only output. Reused by score_judge and by calibrate_judge.py.
    """
    prompt = _judge_prompt(project, legacy_text, rubric)
    return _judge_wizard(prompt) if _judge_backend() == "wizard" else _judge_anthropic(prompt)


def score_judge(project: Path, legacy_text: str, rubric: list[dict]) -> Dimension:
    """rubric: list of {name, description}. Returns averaged 0..1 with per-dimension detail.

    Skipped-with-note (ran=False, excluded from the total) when no judge backend is available, so
    the deterministic score stands on its own. Validate against harbor/_scorer/labeled_set/.
    """
    weight = 1.0
    backend = _judge_backend()
    if backend == "off":
        return Dimension("judge", 0.0, weight,
                         detail="skipped (no judge backend: install dbt-wizard or set ANTHROPIC_API_KEY)",
                         ran=False)
    try:
        scores = judge_raw(project, legacy_text, rubric)
    except Exception as e:
        return Dimension("judge", 0.0, weight, detail=f"judge error ({backend}): {e!r}", ran=False)
    vals = [max(0.0, min(1.0, float(v["score"]))) for v in scores.values()]
    detail = f"[{backend}] " + " · ".join(f"{k} {float(v['score'])*100:.0f}%" for k, v in scores.items())
    return Dimension("judge", sum(vals) / len(vals) if vals else 0.0, weight, detail=detail)


# --- dimension: idiomatic lint (the Phase A quality bar, inside the eval) --


def score_lint(project: Path) -> Dimension:
    """Run the anti-pattern linter (scripts/lint_idiomatic.py, synced next to this file).

    Errors (hardcoded relations, retained control-flow) zero the score; warnings (hooks,
    monoliths, missing layering/tests) soften it. Central to the remediation task, where the
    whole point is lint errors going to zero while parity holds.
    """
    weight = 1.0
    lint = os.environ.get("HARBOR_LINT") or str(Path(__file__).with_name("lint_idiomatic.py"))
    if not Path(lint).exists():
        return Dimension("lint", 0.0, weight, detail="skipped (lint_idiomatic.py not found)", ran=False)
    try:
        out = subprocess.run(["python3", lint, str(project), "--json"], capture_output=True, text=True)
        s = json.loads(out.stdout)["summary"]
    except Exception as e:
        return Dimension("lint", 0.0, weight, detail=f"lint error: {e!r}", ran=False)
    errors, warns = s.get("errors", 0), s.get("warnings", 0)
    score = 0.0 if errors else (1.0 if warns == 0 else 0.6)
    return Dimension("lint", score, weight, detail=f"{errors} error(s), {warns} warning(s)")


# --- orchestration --------------------------------------------------------


def _read_legacy(path: str | None, limit: int = 40000) -> str:
    """Read the legacy artifact - a single file, or all files if it's a directory (e.g. Coalesce nodes)."""
    if not path:
        return ""
    p = Path(path)
    if p.is_dir():
        parts = [f"--- {c.name} ---\n{c.read_text()}"
                 for c in sorted(p.glob("*")) if c.is_file()]
        return "\n".join(parts)[:limit]
    return p.read_text()[:limit]


def score_task(spec: dict) -> Scorecard:
    """spec keys: task, project, marts, inventory?, judge_rubric?, legacy_file?, coverage_threshold?"""
    project = Path(spec["project"])
    card = Scorecard(spec["task"], project)

    ok, log = run_build(project)
    card.add(Dimension("build", 1.0 if ok else 0.0, weight=0.0,  # gate, not weighted
                       detail="dbt build succeeded" if ok else f"dbt build FAILED: {log[-400:]}"))
    if not ok:
        card.add(Dimension("parity", 0.0, 3.0, "build failed"))
        card.add(Dimension("coverage", 0.0, 1.5, "build failed"))
        card.add(Dimension("structural", 0.0, 1.0, "build failed"))
        card.add(Dimension("lint", 0.0, 1.0, "build failed"))
        card.add(Dimension("judge", 0.0, 1.0, "build failed", ran=False))
        return card

    card.add(score_parity(project, spec["marts"]))
    card.add(score_coverage(project, spec))
    card.add(score_structural(project))
    card.add(score_lint(project))
    card.add(score_judge(project, _read_legacy(spec.get("legacy_file")),
                         spec.get("judge_rubric", [])))
    return card


def reward(card: Scorecard, require_lint: bool = False) -> int:
    """Harbor 1/0 gate = correctness: build passed AND every mart matches row-for-row.

    Coverage/structural/judge are quality dimensions in the weighted score, not part of the
    binary gate - an ETL component collapses into fewer dbt models, so a models/units ratio is a
    directional signal, not a pass/fail line. Tasks that opt in with `require_lint` (the
    remediation task) additionally require the idiomatic linter to pass with zero errors.
    """
    b, p = card.get("build"), card.get("parity")
    ok = bool(b and b.score == 1.0 and p and p.score == 1.0)
    if require_lint:
        lint = card.get("lint")
        ok = ok and bool(lint and lint.ran and lint.score == 1.0)
    return int(ok)
