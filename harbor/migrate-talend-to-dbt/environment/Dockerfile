FROM python:3.12-slim

# Verifier + build tooling: dbt-duckdb (warehouse), git (skill install), pyyaml (parsers), curl.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir dbt-duckdb pyyaml

# Don't emit anonymized telemetry from eval runs, and run the Wizard in internal mode.
ENV DO_NOT_TRACK=1 \
    DBT_SEND_ANONYMOUS_USAGE_STATS=False \
    WIZARD_INTERNAL=1

# Preload the migration skills for both agent conventions: /skills (claude-code, via task.toml
# skills_dir) and ~/.dbt/wizard/skills (the dbt Wizard's skills path).
RUN git clone --depth 1 https://github.com/hicham-bab/dbt-legacy-migration-skills.git /tmp/skills \
    && mkdir -p /skills /root/.dbt/wizard/skills \
    && cp -R /tmp/skills/skills/. /skills/ \
    && cp -R /tmp/skills/skills/. /root/.dbt/wizard/skills/ \
    && rm -rf /tmp/skills

# dbt Wizard (fusion) - provides `dbt-wizard exec` for the agent run and the LLM-as-judge via
# dbt-managed inference. Only needed for those (oracle/verifier runs can skip it). Enable with
# --build-arg INSTALL_WIZARD=true; confirm WIZARD_INSTALL_URL for your release channel.
ARG INSTALL_WIZARD=false
ARG WIZARD_INSTALL_URL=https://public.cdn.getdbt.com/fs/install/install.sh
RUN if [ "$INSTALL_WIZARD" = "true" ]; then \
      curl -fsSL "$WIZARD_INSTALL_URL" | sh \
      && (command -v dbt-wizard || ln -sf "$HOME/.local/bin/dbt-wizard" /usr/local/bin/dbt-wizard || true); \
    fi

# dbt-managed inference credentials for the Wizard: OAuth files staged by
# harbor/_scorer/stage_wizard_auth.sh into ./wizard-auth (gitignored). The directory always exists
# (.gitkeep); real tokens are copied in only when staged, and are never committed.
COPY wizard-auth/ /root/.dbt/

# The agent's working files (raw data, legacy Talend job, decisions, empty dbt project + profile).
WORKDIR /app
COPY app/ /app/

# The expected output is NOT copied here - it lives with the verifier (tests/), hidden from the agent.
