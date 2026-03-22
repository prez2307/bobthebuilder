"""Strategy registry - generates BuildSteps from a ProjectContext."""

from __future__ import annotations

from pathlib import Path

from ..models import BuildStep, Ecosystem, ProjectContext, RiskLevel, SubProject
from . import docker, env, go, node, python, ruby, rust

# Makefile targets that indicate a setup/install step
MAKE_SETUP_TARGETS = ["install", "setup", "bootstrap", "deps", "dependencies", "dev", "init"]


def get_steps_for_context(ctx: ProjectContext, docker_flag: bool = False) -> list[BuildStep]:
    """Generate all build steps for a project context, in correct order."""
    steps: list[BuildStep] = []
    has_language_install = False

    # 1. Env file copying (before anything else)
    steps.extend(env.get_steps(ctx))

    # 2. Root-level language-specific install + build
    root_steps = []
    root_steps.extend(node.get_steps(ctx))
    root_steps.extend(python.get_steps(ctx))
    root_steps.extend(go.get_steps(ctx))
    root_steps.extend(rust.get_steps(ctx))
    root_steps.extend(ruby.get_steps(ctx))

    if root_steps:
        has_language_install = True
    steps.extend(root_steps)

    # 3. Subproject steps (ecosystems detected in subdirectories)
    for sub in ctx.subprojects:
        sub_steps = _steps_for_subproject(sub, ctx)
        if sub_steps:
            has_language_install = True
        steps.extend(sub_steps)

    # 4. Makefile targets (only if no language-specific install already handles it)
    if not has_language_install and ctx.makefile_targets:
        make_step = _make_step(ctx.makefile_targets)
        if make_step:
            steps.append(make_step)

    # 5. Docker (only if explicitly requested)
    steps.extend(docker.get_steps(ctx, docker=docker_flag))

    return steps


def _steps_for_subproject(sub: SubProject, ctx: ProjectContext) -> list[BuildStep]:
    """Generate steps for a subdirectory project."""
    steps: list[BuildStep] = []
    working_dir = str(Path(ctx.root) / sub.path)

    # Env files in subproject
    for ef in sub.env_example_files:
        target = ".env"
        target_path = Path(working_dir) / target
        if not target_path.exists():
            steps.append(
                BuildStep(
                    name="copy-env",
                    command=["cp", ef, target],
                    description=f"Copy {sub.path}/{ef} to {sub.path}/{target}",
                    ecosystem=sub.ecosystem,
                    risk_level=RiskLevel.LOW,
                    working_dir=working_dir,
                )
            )

    if sub.ecosystem == Ecosystem.NODE:
        pm = sub.node_package_manager or "npm"
        has_lockfile = pm != "npm"  # simplified: if non-npm, assume lockfile
        if pm == "npm":
            cmd = ["npm", "ci"] if has_lockfile else ["npm", "install"]
        elif pm == "yarn":
            cmd = ["yarn", "install", "--frozen-lockfile"]
        elif pm == "pnpm":
            cmd = ["pnpm", "install", "--frozen-lockfile"]
        elif pm == "bun":
            cmd = ["bun", "install"]
        else:
            cmd = ["npm", "install"]
        steps.append(
            BuildStep(
                name="install-deps",
                command=cmd,
                description=f"Install Node.js deps in {sub.path}",
                ecosystem=Ecosystem.NODE,
                risk_level=RiskLevel.LOW,
                working_dir=working_dir,
            )
        )

    elif sub.ecosystem == Ecosystem.PYTHON:
        tool = sub.python_tool or "pip"
        if tool == "uv":
            cmd = ["uv", "sync"]
        elif tool == "poetry":
            cmd = ["poetry", "install"]
        elif tool == "pipenv":
            cmd = ["pipenv", "install"]
        else:
            cmd = ["pip", "install", "-e", "."]
        steps.append(
            BuildStep(
                name="install-deps",
                command=cmd,
                description=f"Install Python deps in {sub.path}",
                ecosystem=Ecosystem.PYTHON,
                risk_level=RiskLevel.LOW,
                working_dir=working_dir,
            )
        )

    elif sub.ecosystem == Ecosystem.GO:
        steps.append(
            BuildStep(
                name="install-deps",
                command=["go", "mod", "download"],
                description=f"Download Go deps in {sub.path}",
                ecosystem=Ecosystem.GO,
                risk_level=RiskLevel.LOW,
                working_dir=working_dir,
            )
        )
        steps.append(
            BuildStep(
                name="build",
                command=["go", "build", "./..."],
                description=f"Build Go project in {sub.path}",
                ecosystem=Ecosystem.GO,
                risk_level=RiskLevel.LOW,
                working_dir=working_dir,
            )
        )

    elif sub.ecosystem == Ecosystem.RUST:
        steps.append(
            BuildStep(
                name="build",
                command=["cargo", "build"],
                description=f"Build Rust project in {sub.path}",
                ecosystem=Ecosystem.RUST,
                risk_level=RiskLevel.LOW,
                working_dir=working_dir,
            )
        )

    elif sub.ecosystem == Ecosystem.RUBY:
        steps.append(
            BuildStep(
                name="install-deps",
                command=["bundle", "install"],
                description=f"Install Ruby deps in {sub.path}",
                ecosystem=Ecosystem.RUBY,
                risk_level=RiskLevel.LOW,
                working_dir=working_dir,
            )
        )

    return steps


def _make_step(targets: list[str]) -> BuildStep | None:
    """Generate a make step for the first matching setup target."""
    for target in MAKE_SETUP_TARGETS:
        if target in targets:
            return BuildStep(
                name="make-setup",
                command=["make", target],
                description=f"Run make {target}",
                ecosystem=Ecosystem.MAKE,
                risk_level=RiskLevel.MEDIUM,
            )
    return None
