#!/usr/bin/env python3
"""Self-contained CI check for the skills repo (no external deps).

1. Validates each top-level skill's SKILL.md frontmatter:
   - required keys: name, description
   - allowed top-level keys: name, description, license, allowed-tools, metadata
   - name is lowercase-hyphen and equals its folder name
2. Checks every relative markdown link in the repo resolves.

Exit non-zero on any failure.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED = {"name", "description", "license", "allowed-tools", "metadata"}
REQUIRED = {"name", "description"}
# folders that are skills live at repo root and contain a SKILL.md
SKIP_DIRS = {".git", ".github", "ci", "examples"}

errors = []


def frontmatter_keys(text):
    """Return (top-level keys, dict-ish) from the YAML frontmatter block."""
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    block = text[3:end]
    keys, values = [], {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):(.*)$", line)  # top-level (no indent) keys only
        if m:
            keys.append(m.group(1))
            values[m.group(1)] = m.group(2).strip()
    return keys, values


def check_skills():
    found = 0
    for entry in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, entry)
        if not os.path.isdir(d) or entry in SKIP_DIRS:
            continue
        skill = os.path.join(d, "SKILL.md")
        if not os.path.isfile(skill):
            continue
        found += 1
        keys, values = frontmatter_keys(open(skill, encoding="utf-8").read())
        if keys is None:
            errors.append(f"{entry}/SKILL.md: missing or malformed YAML frontmatter")
            continue
        kset = set(keys)
        for req in REQUIRED - kset:
            errors.append(f"{entry}/SKILL.md: missing required frontmatter key '{req}'")
        for extra in kset - ALLOWED:
            errors.append(f"{entry}/SKILL.md: disallowed top-level frontmatter key '{extra}'")
        name = values.get("name", "")
        if name != entry:
            errors.append(f"{entry}/SKILL.md: name '{name}' does not match folder '{entry}'")
        if name and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
            errors.append(f"{entry}/SKILL.md: name '{name}' is not lowercase-hyphen")
    return found


def check_links():
    checked = 0
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in {".git"}]
        for f in files:
            if not f.endswith(".md"):
                continue
            path = os.path.join(base, f)
            text = open(path, encoding="utf-8").read()
            for m in re.finditer(r"\]\(([^)]+)\)", text):
                link = m.group(1).split("#")[0].strip()
                if not link or link.startswith(("http://", "https://", "mailto:")):
                    continue
                target = os.path.normpath(os.path.join(base, link))
                checked += 1
                if not os.path.exists(target):
                    rel = os.path.relpath(path, ROOT)
                    errors.append(f"{rel}: broken link -> {link}")
    return checked


if __name__ == "__main__":
    n_skills = check_skills()
    n_links = check_links()
    if errors:
        print(f"FAILED ({len(errors)} issue(s)):")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print(f"OK: {n_skills} skills valid, {n_links} relative links resolve.")
