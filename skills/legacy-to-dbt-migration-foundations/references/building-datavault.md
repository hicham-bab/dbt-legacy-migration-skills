# Building a Data Vault 2.0 (Step 3, modeling approach = Data Vault)

Generate hubs / links / satellites with the **datavault4dbt** package (Scalefree) — do not hand-roll
hashing/loading SQL — then dimensional **info marts** on top. The legacy→entity mapping is in
[target-modeling.md](target-modeling.md#data-vault-20); this reference distils the package
mechanics. Install datavault4dbt on demand (see [dbt-packages.md](dbt-packages.md)).

> Distilled from Scalefree's **datavault4dbt agent skills** (Apache-2.0,
> `ScalefreeCOM/datavault4dbt-agent-skills`). For deep coverage (all satellite variants, PIT
> cleanup, rehashing, per-adapter config, troubleshooting) install that skill set / read the package
> docs at `dbt_packages/datavault4dbt/docs`.

## Contents

- [Configure the package](#configure-the-package)
- [Choose the entity](#choose-the-entity)
- [The staging-driven pattern](#the-staging-driven-pattern)
- [Layout & materializations](#layout--materializations)
- [Tests & parity](#tests--parity)

## Configure the package

Add `datavault4dbt` to the target `packages.yml`, `dbt deps`, then copy the package's global
variables into `dbt_project.yml` (hash algorithm/datatype, naming, ghost-record settings) and set
per-adapter options. datavault4dbt supports many adapters; timestamp/datatype defaults differ — keep
the package's hash datatype (binary where supported) for smaller, faster joins. **Verify parameter
names against the installed package** (`dbt_packages/datavault4dbt/macros`), not memory.

## Choose the entity

| Legacy unit | Entity | macro |
|---|---|---|
| Stable business key / master entity (customer, product, contract) | **Hub** | `hub` |
| Relationship/association between hubs | **Link** (historized) | `link` |
| Immutable event/transaction with inline attributes | **Non-historized link** | `nh_link` |
| Descriptive attributes with history (SCD / Detect Changes / Update Strategy SCD2) | **Satellite** | `sat_v0` (+ `sat_v1` for load-end-date / PITs) |
| Multiple active values per key | Multi-active satellite | `ma_sat_v0` |
| Code/lookup tables | Reference entities | `ref_hub` / `ref_sat` / `ref_table` |

One business key → one hub. A key that only relates others belongs in a **link**, not a hub. Split
satellites by source system and rate of change (e.g. PII separate from non-PII).

## The staging-driven pattern

Everything is staging-driven: the `stage` macro computes hashkeys + hashdiffs **once**; hubs/links/
sats just reference the pre-computed columns.

```sql
-- 1. staging (view) — compute hashkey (business key) + hashdiff (payload)
{%- set yaml_metadata -%}
source_model: 'src_account'
ldts: 'LOAD_DATE'
rsrc: '!SAP.account'                 -- static literal record source: prefix with !
hashed_columns:
    hk_account_h: [account_id]                          -- hub hashkey
    hd_account_s: {is_hashdiff: true, columns: [name, city, status]}   -- satellite hashdiff
{%- endset -%}
{{ datavault4dbt.stage(yaml_metadata=yaml_metadata) }}
```
```sql
-- 2. hub (incremental)
{{ datavault4dbt.hub(yaml_metadata="hashkey: 'hk_account_h'
business_keys: [account_id]
source_models: stg_account") }}
```
```sql
-- 3. sat_v0 (incremental) — payload must match the hashdiff inputs exactly
{{ datavault4dbt.sat_v0(yaml_metadata="parent_hashkey: 'hk_account_h'
src_hashdiff: 'hd_account_s'
src_payload: [name, city, status]
source_model: 'stg_account'") }}
```
Naming: hub hashkey `hk_<entity>_h`, satellite hashdiff `hd_<entity>_s`, link hashkey `hk_<a>_<b>_l`
(non-historized `..._nl`). Common mistakes: business logic in staging (staging = hashing + light
shaping only); satellite `src_payload` ≠ the hashdiff inputs; missing `rsrc_static` on a
multi-source hub/link; a literal `rsrc` without a leading `!`.

## Layout & materializations

```
01_sources (view) → 02_staging (view) → 03_raw_vault hubs/links/sats (incremental, insert-only)
→ 04_info_delivery dims/facts (table).  00_control: snapshot control + PITs.
```
Raw-vault loads are **insert-only incrementals** (high-water mark) — cheap, append-only, no rebuilds
(the DV compute win). Query performance comes from the info-delivery layer: build **PIT** and
**bridge** tables (`sat_v1` virtual end-dating drives PITs) so BI avoids wide satellite joins;
materialize info marts as `table` and tune per platform
([cloud-detection-and-materializations.md](cloud-detection-and-materializations.md)). The info marts
are dims/facts — build them per [building-kimball.md](building-kimball.md).

## Tests & parity

datavault4dbt technical tests: hashkey `unique` + `not_null` on hubs/links, link→hub referential
integrity, satellite key + load-date uniqueness (via the `arguments:` spec). **Parity (Step 5):**
you can't diff a hub/link/sat against a legacy mart — prove parity at the **info-mart** layer (the
dim/fact built on the vault must match the legacy output), and rely on the raw-vault technical tests
for the vault itself. See [data-validation.md](data-validation.md).
