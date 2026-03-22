# bobthebuilder — Plan v2

## Problem
AI agents (Claude Code, Cursor, Copilot) are terrible at multi-repo development. When a feature spans a React frontend and a Python API (different repos, different ecosystems), the agent wastes tokens reading READMEs, guessing setup commands, retrying failures, and has no concept of how repos relate. There's no tool an agent can call to say "set up these repos so I can work across them."

## Who is the user?
**The primary user is an AI agent.** Bob is a tool that AI agents call to instantly bootstrap a multi-repo workspace. Humans can use it too, but the design optimizes for machine consumption:
- Structured JSON output (not just pretty terminal output)
- Deterministic, no interactive prompts
- Fast — don't waste the agent's context window or wall-clock time
- Exit codes and error messages that an agent can parse and act on

Think of it as a lightweight Brazil Build — you declare your workspace, bob builds everything.

## Core Philosophy
- **Agent-first** — structured output, no interactivity, parseable errors
- **Multi-repo native** — a workspace is the primary unit, not a single repo
- **Fast** — heuristic detection, no AI API calls, seconds not minutes
- **Zero config per repo** — repos don't need to know about bob; bob figures them out
- **One config for the workspace** — `bob.yaml` declares which repos, bob detects how

## How It Works

### 1. `bob init` — Create a workspace
```bash
bob init                                    # interactive: ask which repos
bob init repo1 repo2 repo3                  # from local paths
bob init git@github.com:org/fe.git git@github.com:org/api.git  # clone + detect
```
Scans each repo, detects ecosystems, generates `bob.yaml`:
```yaml
workspace: my-project
repos:
  - path: ./frontend
    url: git@github.com:org/frontend.git
    detected:
      ecosystem: node
      package_manager: npm
  - path: ./backend
    url: git@github.com:org/backend.git
    detected:
      ecosystem: python
      tool: uv
  - path: ./infra
    url: git@github.com:org/infra.git
    detected:
      ecosystem: docker
```

### 2. `bob build` — Set up everything
Reads `bob.yaml`, clones any missing repos, runs the right setup commands for each:
```bash
bob build              # build all repos in workspace
bob build frontend     # build just one
bob build --dry-run    # show plan as JSON, don't execute
```

### 3. `bob status` — What's the state of the workspace?
```bash
bob status             # JSON: which repos are cloned, built, up-to-date
```

## CLI Interface
```
bob init [repos...]          # create workspace, detect ecosystems
bob build [repo] [--dry-run] # install deps + build, all or one repo
bob status                   # workspace state (JSON-friendly)
bob clean                    # remove build artifacts, node_modules, venvs
```

### Output Modes
- Default: human-readable Rich output (colors, spinners, panels)
- `--json`: structured JSON for AI agent consumption
- `--quiet`: minimal output, just errors

## Agent Integration
An AI agent would use bob like this:
```
# Agent clones repos and runs:
bob init ./frontend ./backend
bob build --json

# Output:
{
  "success": true,
  "repos": [
    {"path": "./frontend", "ecosystem": "node", "status": "ready", "duration_s": 3.2},
    {"path": "./backend", "ecosystem": "python", "status": "ready", "duration_s": 1.1}
  ],
  "total_duration_s": 4.3
}
```

If something fails:
```json
{
  "success": false,
  "repos": [
    {"path": "./frontend", "ecosystem": "node", "status": "failed",
     "error": "npm ci failed: missing peer dependency react@18",
     "command": ["npm", "ci"],
     "exit_code": 1,
     "stderr": "..."}
  ]
}
```

The agent gets structured error info and can decide what to do — no token-wasting README parsing.

## Tech Stack
- **Python** with `uv` for our own project management
- **Typer** for CLI
- **Rich** for human-friendly terminal output
- **Pydantic** for models + JSON serialization
- No external AI dependencies

## Project Structure
```
src/bobthebuilder/
  __init__.py
  cli.py              # Typer CLI entrypoint (init, build, status, clean)
  models.py           # Pydantic data models
  detector.py         # Scan a single repo for marker files
  workspace.py        # Multi-repo workspace management (bob.yaml)
  executor.py         # Run commands with streaming output + JSON capture
  output.py           # Output formatting (human vs JSON)
  strategies/
    __init__.py        # Strategy registry
    node.py            # Node.js: npm/yarn/pnpm/bun detection + install
    python.py          # Python: uv/poetry/pipenv/pip detection + install
    go.py              # Go: go mod download + build
    rust.py            # Rust: cargo build
    docker.py          # Docker compose up
    env.py             # .env.example → .env copying
tests/
  test_detector.py
  test_workspace.py
  test_strategies.py
  test_executor.py
```

## Detection Heuristics (per repo)

### Node.js
- Lockfile detection: package-lock.json→npm, yarn.lock→yarn, pnpm-lock.yaml→pnpm, bun.lockb→bun
- Fallback: `packageManager` field in package.json, then default npm
- Commands: `npm ci` / `yarn install --frozen-lockfile` / `pnpm install --frozen-lockfile` / `bun install`
- If `build` script exists in package.json: run it after install

### Python
- Priority: uv.lock→`uv sync`, poetry.lock→`poetry install`, Pipfile.lock→`pipenv install`
- Fallback: requirements.txt→`pip install -r requirements.txt`, pyproject.toml→`pip install -e .`
- Prefer uv over pip when uv is available on PATH

### Go
- go.mod→`go mod download && go build ./...`

### Rust
- Cargo.toml→`cargo build`

### Docker
- docker-compose.yml / compose.yml→`docker compose up -d` (only with `--docker` flag)

### Env files
- .env.example / .env.sample / .env.template→copy to .env if .env doesn't exist

## Execution Order (per repo)
1. Clone (if URL provided and path doesn't exist)
2. Copy env templates
3. Install dependencies (npm/pip/cargo/go)
4. Build (if applicable)

## Security
- Only run commands from a hardcoded allowlist
- Never run sudo, curl|sh, wget|bash
- Never read or transmit .env file contents
- Validate all paths are within workspace root (no traversal)

## bob.yaml Schema
```yaml
workspace: string           # workspace name
repos:                      # list of repos
  - path: string            # relative path from bob.yaml
    url: string | null      # git clone URL (optional)
    detected:               # auto-populated by bob init
      ecosystem: string     # node, python, go, rust, docker
      package_manager: string | null  # npm, yarn, uv, poetry, etc.
    build_steps: []          # override: custom commands (optional)
```

## Dependencies
- typer >= 0.15.0
- rich >= 13.0.0
- pydantic >= 2.0.0
- pyyaml >= 6.0.0
