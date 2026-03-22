"""Strategy registry - generates BuildSteps from a ProjectContext."""

from __future__ import annotations

from ..models import BuildStep, ProjectContext
from . import docker, env, go, node, python, ruby, rust


def get_steps_for_context(ctx: ProjectContext, docker_flag: bool = False) -> list[BuildStep]:
    """Generate all build steps for a project context, in correct order."""
    steps: list[BuildStep] = []

    # 1. Env file copying (before anything else)
    steps.extend(env.get_steps(ctx))

    # 2. Language-specific install + build
    steps.extend(node.get_steps(ctx))
    steps.extend(python.get_steps(ctx))
    steps.extend(go.get_steps(ctx))
    steps.extend(rust.get_steps(ctx))
    steps.extend(ruby.get_steps(ctx))

    # 3. Docker (only if explicitly requested)
    steps.extend(docker.get_steps(ctx, docker=docker_flag))

    return steps
