# Feedback capture (end-of-run)

Every real migration is the best signal for improving these skills. After Step 8 (once
`migration_changes.md` is written), capture lightweight, structured feedback. Keep it optional and
non-blocking, and never send anything anywhere without the user's explicit consent.

## Ask a few short questions

Prompt the user with these (skip any they don't want to answer):

1. Overall, did this migration meet your needs? (1-5)
2. What did you have to fix by hand after the skill finished? (the most useful signal)
3. Did the skill produce anything you expected to change but correctly kept? For example, it may
   split related logic across two or more intermediate models on purpose; that is intended, so note
   if it read as surprising but turned out right.
4. Was data parity proven, partial, or not checked?
5. May we use this migration as an eval fixture to guard against regressions? (yes/no)

## Record it locally

Append one JSON object to `migration_feedback.jsonl` in the migrated project root (create the file
if absent). This stays on the user's machine; it is theirs to share. Schema:

```json
{
  "timestamp": "<ISO-8601>",
  "source_system": "informatica | talend | matillion | coalesce | stored_procedure | other",
  "target_platform": "snowflake | databricks | bigquery | redshift | duckdb | other",
  "agent": "dbt-wizard | claude-code | other",
  "modeling_approach": "layered | kimball | star | datavault",
  "coverage_pct": 0,
  "parity_result": "matched | diffs_explained | diffs_unexplained | not_checked",
  "rating": 0,
  "worked_well": "",
  "needed_manual_fixing": "",
  "correctly_kept": "",
  "share_ok": false,
  "skill_commit": "<git short sha of the skills, if known>"
}
```

## Offer to file it upstream (only with consent)

If the user agrees, offer to open a prefilled GitHub issue using the repo's "Migration report" form:

    https://github.com/hicham-bab/dbt-legacy-migration-skills/issues/new?template=migration_report.yml

Print the link (and the recorded JSON) so the user can review and submit it themselves. Do not post
on their behalf unless they explicitly ask. A reported migration with `share_ok: true` is a candidate
to become a new `harbor/` task or parser fixture, which is how feedback turns into a regression guard.
