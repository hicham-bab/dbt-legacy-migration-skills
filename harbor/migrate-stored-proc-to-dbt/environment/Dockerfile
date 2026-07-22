FROM python:3.12-slim

# Tools the migration needs: dbt-duckdb (warehouse), git (skill install), pyyaml (parsers)
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir dbt-duckdb pyyaml

# Preload the migration skills so the agent (claude-code) can use them.
# skills_dir=/skills in task.toml points the agent here. Self-contained: bake them into the image.
RUN git clone --depth 1 https://github.com/hicham-bab/dbt-legacy-migration-skills.git /tmp/skills \
    && mkdir -p /skills \
    && cp -R /tmp/skills/legacy-to-dbt-migration-foundations /tmp/skills/migrating-* /skills/ \
    && rm -rf /tmp/skills

# The agent's working files (raw data, legacy proc, decisions, empty dbt project + profile).
WORKDIR /app
COPY app/ /app/

# The expected output is NOT copied here — it lives with the verifier (tests/), hidden from the agent.
