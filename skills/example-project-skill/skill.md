# Example project skill

Use this as a template for project-specific guidance you want available in this repo.

## When to use

Use this skill when working on conventions or workflows that are specific to this project.

## Project context

- Replace this section with repo-specific modeling conventions
- Document naming patterns, folder expectations, and testing defaults
- Add warehouse-specific gotchas or deployment notes

## Recommended workflow

1. Read the relevant model and schema files first
2. Check upstream and downstream lineage before changing grain or joins
3. Validate SQL changes with `dbt build --select +model_name+`
4. Add or update tests when behavior changes

## Notes

- Keep skills focused on one job to make them easier to reuse
- Add resource files alongside `skill.md` if you want longer references or examples
