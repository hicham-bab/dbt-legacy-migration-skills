"""Harbor installed-agent adapter for the dbt Wizard (dbt-managed inference).

Runs the real target agent, the dbt Wizard, headlessly via `dbt-wizard exec`, using the
dbt-managed-inference OAuth credentials baked into the image (~/.dbt; staged by
harbor/_scorer/stage_wizard_auth.sh and COPYed in by each task Dockerfile). No raw model API key is
required, which is why this is the preferred agent for evaluating these skills as the Wizard runs
them, not a proxy agent.

Mirrors Harbor's BaseInstalledAgent contract (see src/harbor/agents/installed/aider.py upstream):
name() / get_version_command() / parse_version() / install() / populate_context_post_run() / run().

Registration (recommended): copy this file into your Harbor checkout as
`src/harbor/agents/installed/dbt_wizard.py`, then run:

    harbor run -p harbor/migrate-matillion-to-dbt \
      --agent harbor.agents.installed.dbt_wizard:DbtWizardAgent \
      --build-arg INSTALL_WIZARD=true

Copying it into the harbor package is the clean path because this repo also has a top-level
`harbor/` directory; importing the adapter from *here* would risk that directory shadowing the
installed `harbor` package and breaking `from harbor.agents.installed.base import ...`. Keeping the
canonical copy at harbor/agents/dbt_wizard_agent.py in this repo is just the source to copy from.

CAVEAT (verify against your Wizard build): `dbt-wizard exec` is assumed to write changes into the
working tree. If your build instead emits a diff, set APPLY_AFTER_EXEC=True below so the adapter
runs `dbt-wizard apply --last` afterward.
"""
from __future__ import annotations

import shlex
from typing import override

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

WIZARD_INSTALL_URL = "https://public.cdn.getdbt.com/fs/install/install.sh"
APPLY_AFTER_EXEC = False  # flip to True if `dbt-wizard exec` produces a diff instead of writing files

# Don't emit anonymized telemetry from eval runs; run the Wizard in internal mode (dbt-managed inference).
_WIZARD_ENV = {"WIZARD_INTERNAL": "1", "DO_NOT_TRACK": "1", "DBT_SEND_ANONYMOUS_USAGE_STATS": "False"}


class DbtWizardAgent(BaseInstalledAgent):
    """Runs the dbt Wizard non-interactively (`dbt-wizard exec`) against dbt-managed inference."""

    @staticmethod
    @override
    def name() -> str:
        return "dbt-wizard"

    @override
    def get_version_command(self) -> str | None:
        return "dbt-wizard --version"

    @override
    def parse_version(self, stdout: str) -> str:
        text = stdout.strip()
        for line in text.splitlines():
            if line.strip():
                return line.strip()
        return text

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        # Idempotent: the task image can bake the Wizard in via --build-arg INSTALL_WIZARD=true;
        # if it's already present this is a no-op beyond a version print.
        await self.ensure_system_dependencies(environment, ("curl",))
        await self.exec_as_root(
            environment,
            command=(
                "set -euo pipefail; "
                "if ! command -v dbt-wizard >/dev/null 2>&1; then "
                f"  curl -fsSL {WIZARD_INSTALL_URL} | sh; "
                '  if [ -f "$HOME/.local/bin/env" ]; then . "$HOME/.local/bin/env"; fi; '
                '  command -v dbt-wizard || ln -sf "$HOME/.local/bin/dbt-wizard" /usr/local/bin/dbt-wizard; '
                "fi; dbt-wizard --version"
            ),
        )

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        pass

    @override
    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        escaped = shlex.quote(instruction)
        # model_name is optional: with dbt-managed inference the Wizard picks a default provider;
        # pass provider/model (e.g. anthropic/claude-opus-4-8) to pin it.
        model = f"--model {shlex.quote(self.model_name)} " if self.model_name else ""
        apply = " && dbt-wizard apply --last" if APPLY_AFTER_EXEC else ""
        await self.exec_as_agent(
            environment,
            command=(
                "set -o pipefail; "
                f"dbt-wizard exec {model}{escaped} "
                f"2>&1 | stdbuf -oL tee /logs/agent/wizard.txt{apply}"
            ),
            env=_WIZARD_ENV,
        )
