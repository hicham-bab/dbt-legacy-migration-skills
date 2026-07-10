# Attribution — third-party skills

## datavault4dbt agent skills (Scalefree)

The Data Vault path of these migration skills reuses skills from Scalefree's
**datavault4dbt agent skills**:

- Source: https://github.com/ScalefreeCOM/datavault4dbt-agent-skills
- Author: Scalefree International GmbH
- License: Apache License 2.0

Vendored here (the three needed to produce a Data Vault migration):

- `configuring-datavault4dbt/`
- `using-datavault4dbt/`
- `testing-a-datavault4dbt-project/`

### Modifications made to the vendored copies

Per Apache-2.0 §4, changes are stated:

1. Removed the top-level `user-invocable:` frontmatter key from each `SKILL.md` — the dbt Wizard
   skill validator only accepts `name`, `description`, `license`, `allowed-tools`, and `metadata`.
2. In `using-datavault4dbt/SKILL.md`, trimmed the two "Related skills" bullets that pointed to the
   upstream `troubleshooting-datavault4dbt` and `rehashing-datavault4dbt-entities` skills, which are
   not included in this bundle (they cover fixing/upgrading an existing vault, not producing a
   migration). Install them from the source repo above if you need them.

All other content is unmodified. The upstream Apache-2.0 license governs these three folders; this
repository is also Apache-2.0 (see [LICENSE](LICENSE)).
