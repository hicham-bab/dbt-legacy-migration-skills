FROM python:3.12-slim

# Verifier + build tooling: dbt-duckdb (warehouse), git (skill install), pyyaml (parsers), curl.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir dbt-duckdb pyyaml

# Don't emit anonymized telemetry from eval runs, and run the Wizard in internal mode.
ENV DO_NOT_TRACK=1 \
    DBT_SEND_ANONYMOUS_USAGE_STATS=False \
    WIZARD_INTERNAL=1

# Preload the migration skills for both agent conventions: /skills (claude-code) and
# ~/.dbt/wizard/skills (the dbt Wizard). The remediation skill ships alongside the migration skills.
RUN git clone --depth 1 https://github.com/hicham-bab/dbt-legacy-migration-skills.git /tmp/skills \
    && mkdir -p /skills /root/.dbt/wizard/skills \
    && cp -R /tmp/skills/skills/. /skills/ \
    && cp -R /tmp/skills/skills/. /root/.dbt/wizard/skills/ \
    && rm -rf /tmp/skills

ARG INSTALL_WIZARD=false
ARG WIZARD_INSTALL_URL=https://public.cdn.getdbt.com/fs/install/install.sh
RUN if [ "$INSTALL_WIZARD" = "true" ]; then \
      curl -fsSL "$WIZARD_INSTALL_URL" | sh \
      && (command -v dbt-wizard || ln -sf "$HOME/.local/bin/dbt-wizard" /usr/local/bin/dbt-wizard || true); \
    fi

COPY wizard-auth/ /root/.dbt/

# The agent's working files: the already-migrated (badly) dbt project it must remediate, in /app/project.
WORKDIR /app
COPY app/ /app/

# The expected output is NOT copied here - it lives with the verifier (tests/), hidden from the agent.
