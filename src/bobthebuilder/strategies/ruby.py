"""Ruby setup strategy."""

from __future__ import annotations

from ..models import BuildStep, Ecosystem, ProjectContext, RiskLevel


def get_steps(ctx: ProjectContext) -> list[BuildStep]:
    if Ecosystem.RUBY not in ctx.ecosystems:
        return []

    if ctx.ruby_has_gemfile_lock:
        return [
            BuildStep(
                name="install-deps",
                command=["bundle", "install"],
                description="Install Ruby dependencies with Bundler",
                ecosystem=Ecosystem.RUBY,
                risk_level=RiskLevel.LOW,
            ),
        ]

    # Gemfile but no lock
    return [
        BuildStep(
            name="install-deps",
            command=["bundle", "install"],
            description="Install Ruby dependencies with Bundler",
            ecosystem=Ecosystem.RUBY,
            risk_level=RiskLevel.LOW,
        ),
    ]
