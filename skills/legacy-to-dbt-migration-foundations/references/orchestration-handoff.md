# Orchestration handoff — control flow that dbt does not own (Step 8)

Every migration skill in this set declares legacy control flow "out of scope" for modelling — and
correctly so: an If branch is not a table. But out of dbt's scope is **not** out of the migration's
scope. The branching, retries, notifications, and side effects the legacy tool performed still have
to run somewhere after cutover, and if nobody writes them down they are lost. This reference is
that home. Produce it at Step 8 alongside `migration_changes.md`, as `08_orchestration_handoff.md`.

## Contents

- [Ownership: dbt vs the scheduler](#ownership-dbt-vs-the-scheduler)
- [Input: the typed control-flow edges](#input-the-typed-control-flow-edges)
- [Mapping table: legacy construct → dbt → scheduler](#mapping-table-legacy-construct--dbt--scheduler)
- [Scheduler targets](#scheduler-targets)
- [The batch / run-id problem](#the-batch--run-id-problem)
- [Output template](#output-template)
- [Don't do these things](#dont-do-these-things)

## Ownership: dbt vs the scheduler

| dbt owns | The scheduler owns |
|---|---|
| Intra-project build order, derived from `ref()` — never declared by hand | Cross-system sequencing (ingest → dbt → reverse-ETL → BI refresh) |
| Which models run (`--select`, `--exclude`, tags); tests interleaved via `dbt build` | When the run starts (cron, event, upstream completion); retry policy, backoff, alert routing |
| Skipping downstream models when a parent fails | Branching on failure to a remediation or compensating step |
| Warehouse-side DDL implied by a materialization | Anything with a side effect **outside** the warehouse: files, APIs, emails, tickets |

The dividing line is the side effect. If the action's only result is a relation in the warehouse,
dbt does it. If it touches anything else — object storage, an SFTP drop, a queue, a human — the
scheduler does it, and this document names the owner.

## Input: the typed control-flow edges

`migrating-matillion-to-dbt/scripts/inventory_matillion.py` emits the edges Step 1 discovered, so
they need not be rediscovered from the legacy export:

- `units[].edges` — **every** edge, each `{source, target, kind}` where `kind` is one of
  `flow`, `on_success`, `unconditional`, `on_failure`, `on_true`, `on_false`, `iteration`.
- `control_flow_edges` — a pre-filtered, unit-stamped subset: `{unit, source, target, kind}` for the
  four **non-linear** kinds only (`on_failure`, `on_true`, `on_false`, `iteration`) — the edges
  carrying semantics `ref()` cannot express.
- `summary.control_flow_edge_count` — the count, printed by the script's summary output.

Read both: `control_flow_edges` is the worklist, `units[].edges` holds the linear
`on_success` / `unconditional` chain you still need to reconstruct the intended order.

**`on_failure` is why this document exists.** A success chain survives migration by accident,
because `ref()` reproduces it. A failure branch has no dbt representation at all, so it is dropped
silently — the run is green and the compensating action just never happened. Enumerate every
`on_failure` edge and give each an explicit disposition: reimplemented in the scheduler,
deliberately retired, or open question with a named owner.

> Caveat: pipelines parsed from the DPC/YAML shape emit edges without a `kind` key, so they
> contribute nothing to `control_flow_edges`. A zero count is not proof of no control flow.

## Mapping table: legacy construct → dbt → scheduler

| Legacy construct | dbt equivalent | Scheduler equivalent |
|---|---|---|
| Linear success chain (A → B → C) | `ref()` — the DAG *is* the chain; do not encode order manually | Nothing needed if all three are in one dbt command |
| On-failure branch | **None.** `dbt build` skips downstream on failure but cannot run an alternate path | Failure handler / catch state / `on_failure_callback` |
| If / condition (`on_true` / `on_false`) | None for control. If the condition selects *rows*, it becomes a `where`; if it selects *models*, it becomes `--select` | Conditional / choice step deciding which dbt command to invoke |
| And / Or convergence gate | Implicit: a model with two parents already waits for both (that is And) | Or-semantics (proceed on first parent) needs an explicit scheduler gate — dbt has no Or |
| Retry | `dbt retry` re-runs from the failure point of the previous invocation | Task-level retry count + backoff; prefer this for transient infra faults |
| Iterator / loop over a list | None. Re-express as **set-based SQL** over the driving list, or a single model with a Jinja loop generating one union'd query | Only if each iteration has an external side effect (per-file, per-tenant API call) |
| Notification (email / Slack / SNS) | None — dbt should not send messages | Native notification config, webhook, or on-failure hook |
| Scalar / batch-id generation (`SEQ.NEXTVAL` stamped on rows) | See [the run-id problem](#the-batch--run-id-problem) | Pass its run id in as a dbt var |
| Pre-run DDL truncate | Usually **nothing to do** — a `table` materialization replaces the relation each run; `incremental` handles upsert. Only reach for a `pre_hook` if a real truncate is still required | Not the scheduler's job |
| Post-run file archival / export | None — dbt does not move files | Scheduler task after the dbt task succeeds |
| Cross-pipeline invocation (run-transformation / run-orchestration) | If the callee is in the same dbt project, it collapses into the DAG and disappears | If it crosses projects or systems: job-completion trigger, or dbt Mesh cross-project `ref` |

## Scheduler targets

Capabilities are described generically where an operator name or env-var spelling should be
confirmed against current vendor docs rather than trusted from here.

| Target | Dependencies | On-failure | Pass a run id | One honest limitation |
|---|---|---|---|---|
| **dbt platform jobs** | The dbt DAG within a job; job-completion triggers between jobs | Built-in failure notifications (email / Slack / webhook); a remediation *step* needs an API-triggered second job | Add `--vars` to the job's command; the platform also exposes run identifiers as environment variables (confirm the exact variable names in current docs) | Notification and retry are strong; **branching logic is weak** — it is a job runner, not a workflow engine |
| **Airflow** | Task dependencies; a dbt-aware task-generation library (e.g. Astronomer Cosmos) can expand one dbt project into per-model tasks | `on_failure_callback`, plus `trigger_rule` for tasks that should run *because* an upstream failed | Templated DAG-run fields rendered into `--vars` | Without per-model expansion the whole dbt run is one opaque task — you lose model-level retry and observability |
| **Dagster** | dbt models are surfaced as assets; dependencies come from the dbt manifest | Sensors / hooks reacting to run failure | Run config threaded into the dbt CLI invocation | Asset-centric by design; imperative side-effect steps (archive a file, call an API) fit less naturally than in a task-graph tool |
| **AWS Step Functions** | State machine `Next` transitions; parallel and choice states | `Catch` for error routing, `Retry` for backoff — the most expressive failure branching of the four | Passed in the state input JSON, forwarded to the dbt task as `--vars` | No native dbt execution — you must supply the compute (container task or function) and watch its timeout against long dbt runs |

Pick one and say so in the handoff. "The customer will figure out scheduling" is not a decision.

## The batch / run-id problem

Legacy orchestrations commonly mint a process id from a warehouse sequence
(`SOME_SEQUENCE.NEXTVAL`) at the top of the run and stamp it onto every output row; downstream audit
and reconciliation then group by that id. dbt exposes `invocation_id` (unique per invocation) and
`run_started_at`, so a replacement exists — but you must choose one deliberately.

| Option | How | Tradeoff |
|---|---|---|
| Pass the scheduler's run id in as a var | `dbt build --vars '{batch_id: <scheduler run id>}'`, read as `{{ var('batch_id') }}` | **Recommended.** Ties warehouse rows to the orchestration log, which is what an operator actually wants during an incident. Requires the scheduler to be the sole entry point — an ad-hoc local `dbt build` has no var to pass |
| Derive from `invocation_id` | `{{ invocation_id }}` as the stamp, or hash it to a narrower type | Always available, no external dependency. But it is a dbt-internal identifier: it changes shape from the legacy numeric id, and correlating it back to a scheduler run needs a second lookup |
| Keep the sequence | Read `NEXTVAL` once (a small model or macro) and reference the value | Downstream consumers and existing audit queries keep working unchanged. Retains a warehouse-side stateful object dbt does not manage, and re-running a model can burn ids or, worse, re-stamp rows with a new one |

Whichever you pick, write down the column, its type, and which models stamp it. **Dropping the
stamp silently breaks downstream audit lineage** — the rows still land and every test still passes,
so the loss surfaces weeks later when someone tries to reconcile a specific run and cannot.

## Output template

Write `08_orchestration_handoff.md`:

```markdown
# Orchestration handoff

## Ownership split
| Concern | Owner (dbt / scheduler / retired) | Note |
|---|---|---|

## Build order (the dbt DAG)
- Selector(s) the scheduler invokes: `dbt build --select …` (order comes from `ref()`; not restated)

## Scheduler responsibilities
- Target: [dbt platform jobs / Airflow / Dagster / Step Functions] | Trigger: [cron / event / upstream]
- Steps before and after the dbt invocation:

## Failure handling matrix
<!-- one row per control_flow_edges entry; every on_failure edge must appear -->
| Legacy edge (unit, source → target, kind) | Legacy behaviour | New behaviour | Owner | Status |
|---|---|---|---|---|

## Run-id strategy
- Chosen option + why; column name and type; models that stamp it.

## Notifications
| Event | Channel | Recipients | Configured in |
|---|---|---|---|

## Residual side effects with owners
| Side effect (file, API, email, DDL) | Legacy component | New home | Owner | Date agreed |
|---|---|---|---|---|

## Open questions
- [question] — needs: [name/role] — blocks: [cutover / decommission / nothing]
```

Cross-check the residual side-effect table against the out-of-scope components in the Step 7
[coverage report](coverage-report.md) — anything counted as residual there because it was
orchestration glue must appear here with an owner, or it was dropped rather than handed off.

## Don't do these things

- **Don't model control flow as dbt models.** A model that exists only to sequence other models
  (an empty `select 1` with `ref()` calls to force order) is a scheduler concept smuggled into the
  DAG. It costs a warehouse object and hides the real dependency.
- **Don't drop `on_failure` branches silently.** Every one gets a row in the failure handling matrix
  with a disposition. "Retired" is an acceptable answer; absent is not.
- **Don't reproduce iterators by unrolling into N models.** Twelve near-identical models named
  `..._01` through `..._12` is a loop that escaped. Go set-based, or generate one query with Jinja.
- **Don't leave the run-id decision implicit.** If you did not choose, you chose to drop it.
- **Don't assume `dbt retry` matches the legacy retry.** Legacy retry often re-ran a step with a
  side effect (re-sending a file); `dbt retry` resumes a build. Confirm idempotency first.
- **Don't hand over a migration with no scheduler story and call it done.** Green models that
  nothing triggers are not a migration; they are a proof of concept. This document, with an owner
  against every scheduler responsibility, is part of the deliverable.
