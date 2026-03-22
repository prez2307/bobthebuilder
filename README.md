# bobthebuilder

Automatically set up any project for local development. Clone a repo, run `bob`, done.

**Designed for AI agents** — structured JSON output, deterministic behavior, no interactive prompts. Also works great for humans.

## The Problem

You clone 2-3 related repos. Each one has a different ecosystem — Node.js frontend, Python API, Go service. You spend 15 minutes reading READMEs, figuring out package managers, running install commands. AI agents waste even more time: parsing READMEs, guessing commands, retrying failures.

## The Solution

```bash
# Single repo
cd my-project
bob build

# Multi-repo workspace
bob init ./frontend ./backend ./infra
bob build
```

Bob detects the ecosystem from marker files (package.json, pyproject.toml, go.mod, Cargo.toml, etc.) and runs the right setup commands. No config needed in the target repos.

## Install

```bash
# With uv (recommended)
uv tool install bobthebuilder

# With pip
pip install bobthebuilder

# From source
git clone https://github.com/your-org/bobthebuilder.git
cd bobthebuilder
uv sync
```

## Usage

### Single Repo

```bash
cd my-project
bob build              # detect and install deps
bob build --dry-run    # show what would run
bob build --json       # structured output for AI agents
```

### Multi-Repo Workspace

```bash
# Create a workspace (generates bob.yaml)
bob init ./frontend ./backend

# Build everything
bob build

# Build one repo
bob build frontend

# Show workspace status
bob status
```

### Generated bob.yaml

```yaml
workspace: my-project
repos:
  - path: ./frontend
    detected:
      ecosystem: node
      package_manager: npm
  - path: ./backend
    detected:
      ecosystem: python
      package_manager: uv
```

### JSON Output (for AI agents)

```bash
bob build --json
```

```json
{
  "success": true,
  "total_duration_s": 4.3,
  "steps": [
    {"step": "install-deps", "success": true, "duration_s": 3.2, "command": ["npm", "ci"]},
    {"step": "install-deps", "success": true, "duration_s": 1.1, "command": ["uv", "sync"]}
  ]
}
```

On failure:

```json
{
  "success": false,
  "total_duration_s": 2.1,
  "steps": [
    {"step": "install-deps", "success": false, "exit_code": 1,
     "error": "npm ci failed", "stderr": "...", "command": ["npm", "ci"]}
  ]
}
```

## Supported Ecosystems

| Ecosystem | Detection | Install Command |
|-----------|-----------|-----------------|
| Node.js (npm) | `package-lock.json` | `npm ci` |
| Node.js (yarn) | `yarn.lock` | `yarn install --frozen-lockfile` |
| Node.js (pnpm) | `pnpm-lock.yaml` | `pnpm install --frozen-lockfile` |
| Node.js (bun) | `bun.lockb` | `bun install` |
| Python (uv) | `uv.lock` | `uv sync` |
| Python (poetry) | `poetry.lock` | `poetry install` |
| Python (pipenv) | `Pipfile.lock` | `pipenv install` |
| Python (pip) | `requirements.txt` | `pip install -r requirements.txt` |
| Go | `go.mod` | `go mod download && go build ./...` |
| Rust | `Cargo.toml` | `cargo build` |
| Docker | `docker-compose.yml` | `docker compose up -d` (with `--docker`) |

Also handles:
- `.env.example` → `.env` copying
- `build` script detection in package.json
- Makefile target detection

## Security

- Only runs commands from a hardcoded allowlist (npm, pip, cargo, go, etc.)
- Never runs `sudo`, `curl | sh`, `rm`, or other dangerous commands
- Never reads or transmits `.env` file contents
- All commands validated before execution

## Development

```bash
git clone https://github.com/your-org/bobthebuilder.git
cd bobthebuilder
uv sync

# Run unit tests
uv run pytest tests/ -m "not integration"

# Run integration tests (clones real repos)
uv run pytest tests/ -m integration

# Run all tests
uv run pytest tests/
```

## License

MIT
