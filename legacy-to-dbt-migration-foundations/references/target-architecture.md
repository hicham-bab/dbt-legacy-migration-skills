# Choosing the target architecture (Step 2)

After the legacy workload is mapped (Step 1) and **before** generating any dbt models, ask the
person doing the migration **which target modeling architecture** to build. The answer reshapes how
you classify the workload (rest of Step 2), how you generate models (Step 3), and which tests/
materializations you apply (Step 4). Do not assume — a migration is the natural moment to decide
whether to re-architect, and it's the migrator's call.

## Contents

- [The question to ask](#the-question-to-ask)
- [Data Vault 2.0](#data-vault-20)
- [Kimball dimensional](#kimball-dimensional)
- [Star schema](#star-schema)
- [Layered fallback (no re-architecture)](#layered-fallback-no-re-architecture)
- [Tests, docs & contracts per architecture](#tests-docs--contracts-per-architecture)
- [Performance cheat-sheet](#performance-cheat-sheet)

## The question to ask

Present the mapped inventory, then ask the migrator to pick one of the three target architectures:

> "I've mapped the legacy workload. Before I build the dbt models, which target architecture should
> I follow?
> - **Data Vault 2.0** — hubs / links / satellites (auditable, insert-only), with dimensional info
>   marts on top. Best for highly-governed, multi-source, audit-heavy warehouses.
> - **Kimball dimensional** — conformed dimensions + fact tables (full bus architecture, SCD2).
>   Best when many business processes share dimensions and BI is the goal.
> - **Star schema** — facts + dimensions for a focused subject area, minimal ceremony. Good for a
>   single mart / quick BI."

Whichever they choose, the migration still applies data **tests, docs, and contracts** (Step 4) —
see [tests, docs & contracts per architecture](#tests-docs--contracts-per-architecture). If the
migrator explicitly wants **no re-architecture** (a faithful like-for-like port), fall back to the
plain layered structure in [layer-classification.md](layer-classification.md).

Guidance to offer:
- **Kimball ⊃ star schema.** Kimball dimensional *produces* star schemas; the difference is
  governance — Kimball adds conformed dimensions and a bus matrix across processes, "pragmatic star"
  is one star for one subject area without that ceremony. If they're unsure between the two and
  there's one subject area, pick pragmatic star; if several processes share customer/product/date
  dimensions, pick Kimball.
- **Re-architecting adds risk and cost.** Layered is the safe default and the easiest to prove at
  parity (Step 5), because the mart grain still matches the legacy output. Data Vault especially is
  a large structural change — recommend it only when auditability/multi-source integration is an
  explicit requirement, and confirm the team will maintain a vault.
- The choice is per-project (or per-Mesh-domain), not per-model. Record it; it drives Steps 3-4.

## Data Vault 2.0

A Data Vault splits data into **hubs** (business keys), **links** (relationships), and **satellites**
(descriptive history), loaded insert-only, with dimensional **info marts** built on top. Use the
**datavault4dbt** package (Scalefree) — do not hand-roll hashing/loading SQL.

**Reuse the datavault4dbt skills — don't reinvent them.** This skill decides the *modeling* (which
legacy unit becomes which entity); the package mechanics come from the Scalefree skill set
(Apache-2.0), bundled here as the three needed for a migration:
- `configuring-datavault4dbt` — `packages.yml`, global variables, hashing, per-adapter setup (do this first)
- `using-datavault4dbt` — building stage/hub/link/satellite/PIT models (the YAML-metadata macro pattern)
- `testing-a-datavault4dbt-project` — hub/link/satellite technical tests

(The upstream `troubleshooting-datavault4dbt` and `rehashing-datavault4dbt-entities` skills aren't
bundled — they're for fixing/upgrading an existing vault, not producing a migration; install them
from `ScalefreeCOM/datavault4dbt-agent-skills` if needed.)

**Map the legacy workload → Data Vault entities:**

| Legacy unit (from Step 1) | Data Vault entity | datavault4dbt macro |
|---|---|---|
| A stable business key / master entity (customer, product, contract, account) | **Hub** | `hub` |
| A relationship/association between entities (order↔customer↔product) | **Link** (historized) | `link` |
| An immutable event/transaction with inline attributes (payment, click) | **Non-historized link** | `nh_link` |
| Descriptive attributes with history (SCD / Detect Changes / Update Strategy SCD2) | **Satellite** | `sat_v0` (+ `sat_v1`) |
| Multiple active values per key (several phone numbers) | Multi-active satellite | `ma_sat_v0` |
| Code/lookup tables (currency, country) | Reference entities | `ref_hub` / `ref_sat` / `ref_table` |
| The legacy final mart / report output | **Info-mart** dim/fact on top of the vault | plain dbt model (see Kimball/star) |

**Layering & materializations** (per datavault4dbt's project layout):
`01_sources` (view) → `02_staging` (view; the `stage` macro computes hashkeys/hashdiffs once) →
`03_raw_vault` hubs/links/sats (**incremental, insert-only**) → `04_info_delivery` dims/facts
(**table**). Snapshot control + PITs in `00_control`.

**Performance:**
- Raw vault loads are **insert-only incrementals** with a high-water mark — cheap, append-only, no
  rebuilds. This is the DV compute win: you never re-transform history.
- Query performance comes from the info-delivery layer, not the raw vault: build **PIT** (point-in-
  time) and **bridge** tables (`sat_v1` virtualized end-dating drives PITs) so BI queries avoid
  wide satellite joins. Materialize info marts as `table`.
- Hashkeys make joins uniform; keep the package's hash datatype (binary where the adapter supports
  it) for smaller, faster joins — see `configuring-datavault4dbt`.
- Apply the platform tuning from [cloud-detection-and-materializations.md](cloud-detection-and-materializations.md)
  to the info marts (partition/cluster facts by date, cluster dims by key).

**Parity note (Step 5):** you can't diff a hub/link/sat against a legacy mart directly. Prove parity
at the **info-mart** layer — the dim/fact built on the vault must match the legacy output — and rely
on the datavault4dbt hashkey uniqueness/not-null tests for the raw vault itself.

## Kimball dimensional

Conformed **dimensions** shared across business processes + **fact** tables, laid out as star schemas.

**Map the legacy workload → dimensional model:**
- Master/reference entities (customer, product, date, store) → **dimensions** (`dim_`). History-
  tracking dimensions (legacy SCD2 / Detect Changes / Update Strategy) → **dbt snapshots** feeding a
  Type-2 `dim_` (with `valid_from`/`valid_to`/`is_current`).
- Business-process events/measures (orders, sales, shipments) → **fact** tables (`fct_`) at a
  declared grain; foreign keys are the dimensions' **surrogate keys**.
- Surrogate keys via `{{ dbt_utils.generate_surrogate_key([...]) }}` on the natural key (Type-1) or
  natural key + effective date (Type-2). Facts reference the dimension surrogate key, not the
  natural key.
- **Conformed dimensions:** if several legacy jobs/marts use the same entity, build **one** shared
  dimension and reference it from every fact (a mini bus matrix). In a Mesh, put conformed dims in
  the producer with enforced contracts.

**Layering:** source → `stg_` (view) → `int_` (joins/derivations) → `dim_`/`fct_` marts (table/
incremental). Snapshots live in `snapshots/`.

**Performance:**
- **Facts:** `incremental` with `merge`/`insert_overwrite` on the date partition; partition + cluster
  by the date and the highest-cardinality FK (see the platform table in cloud-detection). Never full-
  rebuild a large fact each run.
- **Dimensions:** usually `table` (smaller); cluster by surrogate/natural key. Type-2 dims come from
  snapshots (cheap incremental capture) rather than recomputed history.
- Keep facts **narrow** (keys + measures + degenerate dims); push descriptive attributes into dims to
  avoid re-scanning wide facts.

## Star schema

A single star for one subject area: one (or few) `fct_` + its `dim_`s, minimal governance. Same
generation as Kimball but without the conformed-dimension/bus-matrix ceremony — good for a focused
mart or a quick migration to BI-friendly shape.

- Facts + dimensions as above; surrogate keys optional (natural keys acceptable for a self-contained
  mart). SCD2 only where the legacy tracked history; otherwise Type-1 (overwrite) dims.
- **Snowflake-schema variant:** if you keep dimensions normalized (dim → sub-dim), note the extra
  joins; prefer denormalized star dims for query performance unless storage/maintenance argues
  otherwise.
- **Performance:** same as Kimball facts/dims (partition/cluster the fact by date + main FK; dims as
  clustered tables). Simpler DAG = cheaper to build and validate.

## Layered fallback (no re-architecture)

If the migrator declines all three paradigms and wants a faithful like-for-like port, use the plain
layered structure from [layer-classification.md](layer-classification.md): source → staging (`stg_`,
view) → intermediate (`int_`) → mart (`fct_`/`dim_`, table/incremental). The legacy target maps 1:1
to a mart, so parity is the most straightforward. Tests/docs/contracts still apply (below).

## Tests, docs & contracts per architecture

Whichever paradigm is chosen, Step 4 still applies — adapted to the architecture:

| | Data Vault | Kimball / Star |
|---|---|---|
| **Data tests** | Hashkey `unique` + `not_null` on hubs/links; link→hub `relationships`; satellite key+ldts uniqueness — via the `testing-a-datavault4dbt-project` skill. Plus grain tests on the info marts. | `unique` + `not_null` on the dim surrogate key and the fact grain; `relationships` from every fact FK to its dim; `accepted_values` on low-cardinality columns — via the `arguments:` spec ([dbt-best-practices.md](dbt-best-practices.md)). |
| **Docs** | Model + column descriptions on staging, entities, and info marts; state each hub's business key and each satellite's source/rate-of-change. | Model + column descriptions on every dim and fact; state the fact **grain** explicitly and each dimension's SCD type. |
| **Contracts** | `contract: enforced` on the **public info marts** (the query-facing dims/facts). The raw vault is internal. | `contract: enforced` on published dims and facts (especially conformed dims in a Mesh producer); version them. |

Data Vault history is captured by satellites (insert-only), so SCD is inherent; Kimball/star track
history via **snapshots** feeding Type-2 dims. See [dbt-best-practices.md](dbt-best-practices.md)
for the test/doc/contract syntax.

## Performance cheat-sheet

Regardless of paradigm, apply [cloud-detection-and-materializations.md](cloud-detection-and-materializations.md):
- **Incremental, not rebuild**, for anything large and frequently run (DV raw vault, Kimball facts).
- **Partition + cluster** the big tables (facts / info-mart facts) by date + main join key; cluster
  dims by key.
- **Views** for cheap upstream shaping (staging), **tables** for end-user query surfaces (dims/facts/
  info marts), **insert-only incrementals** for history (DV satellites, snapshots).
- Prove parity at the **query-facing layer** (mart / info-mart), which is where the legacy output
  has an equivalent grain.
