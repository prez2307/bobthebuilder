"""Doctor - diagnose tool versions and environment health, with auto-fix."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .detector import detect_project
from .models import Ecosystem


# Map of ecosystem -> list of (tool_name, version_args)
TOOL_CHECKS: dict[str, list[tuple[str, list[str]]]] = {
    "node": [
        ("node", ["node", "--version"]),
        ("npm", ["npm", "--version"]),
        ("yarn", ["yarn", "--version"]),
        ("pnpm", ["pnpm", "--version"]),
        ("bun", ["bun", "--version"]),
    ],
    "python": [
        ("python", ["python3", "--version"]),
        ("pip", ["pip3", "--version"]),
        ("uv", ["uv", "--version"]),
        ("poetry", ["poetry", "--version"]),
        ("pipenv", ["pipenv", "--version"]),
    ],
    "go": [
        ("go", ["go", "version"]),
    ],
    "rust": [
        ("cargo", ["cargo", "--version"]),
        ("rustc", ["rustc", "--version"]),
    ],
    "ruby": [
        ("ruby", ["ruby", "--version"]),
        ("bundler", ["bundle", "--version"]),
    ],
    "docker": [
        ("docker", ["docker", "--version"]),
        ("docker-compose", ["docker", "compose", "version"]),
    ],
}

REQUIRED_TOOLS: dict[str, set[str]] = {
    "node": {"node"},
    "python": {"python"},
    "go": {"go"},
    "rust": {"cargo", "rustc"},
    "ruby": {"ruby", "bundler"},
    "docker": {"docker"},
}

VERSION_FILES: dict[str, list[tuple[str, str]]] = {
    "node": [(".nvmrc", "node"), (".node-version", "node")],
    "python": [(".python-version", "python")],
    "ruby": [(".ruby-version", "ruby")],
    "rust": [("rust-toolchain.toml", "rustc"), ("rust-toolchain", "rustc")],
}

# Install commands for missing tools — safe, commonly available installers
INSTALL_COMMANDS: dict[str, list[str]] = {
    "pnpm": ["npm", "install", "-g", "pnpm"],
    "yarn": ["npm", "install", "-g", "yarn"],
    "bun": ["npm", "install", "-g", "bun"],
    "uv": ["pip3", "install", "uv"],
    "poetry": ["pip3", "install", "poetry"],
    "pipenv": ["pip3", "install", "pipenv"],
    "bundler": ["gem", "install", "bundler"],
}

# Tools that can update themselves to a specific version
VERSION_INSTALL_COMMANDS: dict[str, str] = {
    "node": "nvm install {version}",
    "python": "pyenv install {version}",
    "ruby": "rbenv install {version}",
    "rustc": "rustup default {version}",
}


@dataclass
class ToolCheck:
    """Result of checking a single tool."""

    name: str
    installed: bool
    version: str = ""
    required: bool = False
    wanted_version: str = ""

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "installed": self.installed,
            "required": self.required,
        }
        if self.version:
            d["version"] = self.version
        if self.wanted_version:
            d["wanted_version"] = self.wanted_version
        return d


@dataclass
class DoctorResult:
    """Result of doctor check for one repo."""

    repo: str
    ecosystem: str
    checks: list[ToolCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(c.installed for c in self.checks if c.required)

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "ecosystem": self.ecosystem,
            "healthy": self.healthy,
            "checks": [c.to_dict() for c in self.checks],
            "warnings": self.warnings,
        }


def _get_version(cmd: list[str]) -> str | None:
    """Run a version command and return the output, or None if not found."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _read_version_file(path: Path) -> str:
    """Read a version file and return its content."""
    try:
        return path.read_text().strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def check_repo(repo_path: Path) -> DoctorResult:
    """Run doctor checks for a single repo (including all subproject ecosystems)."""
    ctx = detect_project(repo_path)
    primary_eco = None
    for eco in ctx.root_ecosystems:
        if eco not in (Ecosystem.MAKE, Ecosystem.DOCKER):
            primary_eco = eco
            break
    if primary_eco is None and ctx.ecosystems:
        primary_eco = ctx.ecosystems[0]

    eco_name = primary_eco.value if primary_eco else "unknown"
    result = DoctorResult(repo=repo_path.name, ecosystem=eco_name)

    if primary_eco is None and not ctx.subprojects:
        result.warnings.append("No ecosystem detected")
        return result

    # Collect ALL needed tools across root + subprojects
    needed_tools = _tools_needed_for_repo(ctx)
    checked_tools: set[str] = set()

    # Collect all ecosystems to check (root + subprojects)
    all_eco_names: set[str] = set()
    if primary_eco:
        all_eco_names.add(eco_name)
    for sub in ctx.subprojects:
        if sub.ecosystem not in (Ecosystem.MAKE, Ecosystem.DOCKER):
            all_eco_names.add(sub.ecosystem.value)
            # Add subproject-specific tools to needed set
            if sub.ecosystem == Ecosystem.PYTHON:
                needed_tools.add("python")
                if sub.python_tool and sub.python_tool != "pip":
                    needed_tools.add(sub.python_tool)
            elif sub.ecosystem == Ecosystem.RUST:
                needed_tools.add("cargo")
                needed_tools.add("rustc")
            elif sub.ecosystem == Ecosystem.GO:
                needed_tools.add("go")
            elif sub.ecosystem == Ecosystem.RUBY:
                needed_tools.add("ruby")
                needed_tools.add("bundler")

    # Check tools across all ecosystems
    for eco in all_eco_names:
        tool_checks = TOOL_CHECKS.get(eco, [])
        required = REQUIRED_TOOLS.get(eco, set())

        for tool_name, version_cmd in tool_checks:
            if tool_name in checked_tools:
                continue
            if tool_name not in needed_tools and tool_name not in required:
                continue

            version = _get_version(version_cmd)
            check = ToolCheck(
                name=tool_name,
                installed=version is not None,
                version=version or "",
                required=tool_name in required or tool_name in needed_tools,
            )
            result.checks.append(check)
            checked_tools.add(tool_name)

    # Check version files
    for eco in all_eco_names:
        for version_file, tool_name in VERSION_FILES.get(eco, []):
            vf_path = repo_path / version_file
            if vf_path.exists():
                wanted = _read_version_file(vf_path)
                if wanted:
                    for check in result.checks:
                        if check.name == tool_name:
                            check.wanted_version = wanted
                            break

    # Docker check if docker-compose is present
    if ctx.has_docker_compose and "docker" not in checked_tools:
        for tool_name, version_cmd in TOOL_CHECKS.get("docker", []):
            if tool_name not in checked_tools:
                version = _get_version(version_cmd)
                result.checks.append(ToolCheck(
                    name=tool_name,
                    installed=version is not None,
                    version=version or "",
                    required=True,
                ))
                checked_tools.add(tool_name)

    # Warnings
    if "node" in all_eco_names and not (repo_path / "node_modules").exists():
        result.warnings.append("node_modules not found — run 'bob build' first")
    if "python" in all_eco_names:
        has_venv = (repo_path / ".venv").exists() or (repo_path / "venv").exists()
        if not has_venv and ctx.python_tool not in ("uv", "poetry"):
            # Check subprojects too
            sub_has_uv_poetry = any(
                s.python_tool in ("uv", "poetry") for s in ctx.subprojects if s.ecosystem == Ecosystem.PYTHON
            )
            if not sub_has_uv_poetry:
                result.warnings.append("No virtual environment found — consider using 'uv' or 'poetry'")

    return result


@dataclass
class FixAction:
    """A fix that was attempted."""

    tool: str
    command: list[str]
    success: bool
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "command": self.command,
            "success": self.success,
            "message": self.message,
        }


@dataclass
class FixResult:
    """Result of doctor --fix for a repo."""

    repo: str
    fixes: list[FixAction] = field(default_factory=list)
    still_broken: list[str] = field(default_factory=list)

    @property
    def all_fixed(self) -> bool:
        return len(self.still_broken) == 0

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "all_fixed": self.all_fixed,
            "fixes": [f.to_dict() for f in self.fixes],
            "still_broken": self.still_broken,
        }


def fix_repo(repo_path: Path) -> FixResult:
    """Attempt to fix missing tools for a repo."""
    doctor_result = check_repo(repo_path)
    fix_result = FixResult(repo=repo_path.name)

    for check in doctor_result.checks:
        if check.installed:
            continue
        if not check.required:
            continue

        # Try to install the missing tool
        install_cmd = INSTALL_COMMANDS.get(check.name)
        if install_cmd:
            action = _try_install(check.name, install_cmd)
            fix_result.fixes.append(action)
            if not action.success:
                fix_result.still_broken.append(check.name)
        else:
            # Can't auto-install — provide guidance
            hint = _install_hint(check.name)
            fix_result.fixes.append(FixAction(
                tool=check.name,
                command=[],
                success=False,
                message=hint,
            ))
            fix_result.still_broken.append(check.name)

    # Handle docker compose for services
    ctx = detect_project(repo_path)
    if ctx.has_docker_compose:
        compose_running = _check_docker_services(repo_path)
        if not compose_running:
            fix_result.fixes.append(FixAction(
                tool="docker-services",
                command=["docker", "compose", "up", "-d"],
                success=False,
                message="Docker services not running. Run 'docker compose up -d' to start them.",
            ))

    return fix_result


def _try_install(tool_name: str, command: list[str]) -> FixAction:
    """Attempt to install a tool."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            # Verify it's now available
            return FixAction(
                tool=tool_name,
                command=command,
                success=True,
                message=f"Installed {tool_name}",
            )
        return FixAction(
            tool=tool_name,
            command=command,
            success=False,
            message=result.stderr.strip()[:200] or f"Install failed with exit code {result.returncode}",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return FixAction(
            tool=tool_name,
            command=command,
            success=False,
            message=str(e),
        )


def _install_hint(tool_name: str) -> str:
    """Return a human-readable install hint for a tool that can't be auto-installed."""
    hints = {
        "node": "Install Node.js: https://nodejs.org/ or use 'nvm install --lts'",
        "python": "Install Python: https://python.org/ or use 'pyenv install 3.12'",
        "go": "Install Go: https://go.dev/dl/ or use 'brew install go'",
        "cargo": "Install Rust: https://rustup.rs/ — run 'curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh'",
        "rustc": "Install Rust: https://rustup.rs/",
        "ruby": "Install Ruby: https://ruby-lang.org/ or use 'rbenv install'",
        "docker": "Install Docker: https://docs.docker.com/get-docker/",
        "npm": "npm comes with Node.js — install Node first",
    }
    return hints.get(tool_name, f"Install {tool_name} manually")


def _check_docker_services(repo_path: Path) -> bool:
    """Check if docker compose services are running."""
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--status=running", "-q"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _tools_needed_for_repo(ctx) -> set[str]:
    """Determine which specific tools are needed based on detection."""
    needed: set[str] = set()

    for eco in ctx.root_ecosystems:
        if eco == Ecosystem.NODE:
            pm = ctx.node_package_manager or "npm"
            needed.add("node")
            needed.add(pm)
        elif eco == Ecosystem.PYTHON:
            needed.add("python")
            tool = ctx.python_tool
            if tool and tool != "pip":
                needed.add(tool)
        elif eco == Ecosystem.GO:
            needed.add("go")
        elif eco == Ecosystem.RUST:
            needed.add("cargo")
            needed.add("rustc")
        elif eco == Ecosystem.RUBY:
            needed.add("ruby")
            needed.add("bundler")
        elif eco == Ecosystem.DOCKER:
            needed.add("docker")

    return needed
