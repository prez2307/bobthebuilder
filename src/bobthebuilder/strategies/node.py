"""Node.js setup strategy."""

from __future__ import annotations

from ..models import BuildStep, Ecosystem, ProjectContext, RiskLevel

# Scripts that should be auto-run after install
AUTO_RUN_SCRIPTS = {"build", "prepare"}


def get_steps(ctx: ProjectContext) -> list[BuildStep]:
    if Ecosystem.NODE not in ctx.ecosystems:
        return []

    steps: list[BuildStep] = []
    pm = ctx.node_package_manager or "npm"
    has_lockfile = pm != "npm" or any(
        m.path == "package-lock.json" for m in ctx.marker_files
    )

    # Install command depends on package manager and lockfile presence
    install_cmd = _install_command(pm, has_lockfile)
    steps.append(
        BuildStep(
            name="install-deps",
            command=install_cmd,
            description=f"Install Node.js dependencies with {pm}",
            ecosystem=Ecosystem.NODE,
            risk_level=RiskLevel.LOW,
        )
    )

    # Auto-run build script if present
    for script in ctx.node_scripts:
        if script in AUTO_RUN_SCRIPTS:
            steps.append(
                BuildStep(
                    name="build",
                    command=[pm, "run", script],
                    description=f"Run {script} script",
                    ecosystem=Ecosystem.NODE,
                    risk_level=RiskLevel.LOW,
                )
            )
            break  # only run one build-like script

    return steps


def _install_command(pm: str, has_lockfile: bool) -> list[str]:
    if pm == "npm":
        return ["npm", "ci"] if has_lockfile else ["npm", "install"]
    if pm == "yarn":
        return ["yarn", "install", "--frozen-lockfile"] if has_lockfile else ["yarn", "install"]
    if pm == "pnpm":
        return ["pnpm", "install", "--frozen-lockfile"] if has_lockfile else ["pnpm", "install"]
    if pm == "bun":
        return ["bun", "install"]
    return ["npm", "install"]
