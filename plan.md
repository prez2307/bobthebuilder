# bobthebuilder — Revised Plan

## Problem
You clone a repo. You have to read the README, figure out if it's npm or pip or uv or poetry, run install commands, copy .env files, maybe run a build step. This takes 5-30 minutes and is pure friction.

## Core Philosophy (revised)
- **No AI API calls** — no Claude API, no OpenAI, no approval flows
- **Fast** — detect and run in seconds, not minutes
- **Local-first** — optionally use a small local model (ollama) for README parsing, but the 80% case should work with zero AI
- **Zero config** — no bobthebuilder config needed in the target repo
- **Just do it** — detect the ecosystem, run the right commands, done

## How It Works
1. **Detect**: Scan for marker files (package.json, pyproject.toml, go.mod, Cargo.toml, etc.)
2. **Plan**: Use hardcoded heuristics to pick the right commands (no AI needed for the common case)
   - `package-lock.json` exists → `npm ci`
   - `yarn.lock` exists → `yarn install`
   - `uv.lock` exists → `uv sync`
   - `pyproject.toml` + no lockfile → `uv sync` or `pip install -e .`
   - `requirements.txt` → `pip install -r requirements.txt`
   - `go.mod` → `go mod download`
   - `Cargo.toml` → `cargo build`
   - `.env.example` exists → copy to `.env` if `.env` doesn't exist
   - `Makefile` with `install`/`setup`/`dev` target → run it
3. **Execute**: Run the commands, stream output with nice formatting
4. **Optional AI fallback**: If `--ai` flag is passed AND ollama is available, parse the README for non-obvious setup steps

## CLI Interface
```
bob                    # detect and set up current directory
bob /path/to/repo      # set up a specific directory
bob --dry-run          # show what would be done, don't execute
bob --ai               # use local ollama model to parse README for extra steps
bob --verbose          # show more detail
```

## Tech Stack
- **Python** with `uv` for project management
- **Typer** for CLI
- **Rich** for terminal output (spinners, colors, panels)
- No required external AI dependencies — ollama is optional

## Project Structure
```
src/bobthebuilder/
  __init__.py
  cli.py           # Typer CLI entrypoint
  detector.py      # Scan for marker files, produce ProjectContext
  planner.py       # Heuristic-based plan generation (no AI)
  executor.py      # Run commands with streaming output
  models.py        # Pydantic data models
  ai.py            # Optional ollama integration for README parsing
  strategies/
    __init__.py
    node.py        # Node.js setup strategy
    python.py      # Python setup strategy
    go.py          # Go setup strategy
    rust.py        # Rust setup strategy
    docker.py      # Docker compose strategy
    make.py        # Makefile strategy
    env.py         # .env file handling
tests/
  test_detector.py
  test_planner.py
  test_strategies.py
```

## Detection → Strategy Mapping
Each ecosystem has a **strategy** that knows how to generate the right BuildSteps:

### Node Strategy
- Detect package manager from lockfile: npm (package-lock.json), yarn (yarn.lock), pnpm (pnpm-lock.yaml), bun (bun.lockb)
- If no lockfile, check for `packageManager` field in package.json, fall back to npm
- Run install command
- Check for `build` script in package.json, run if present
- Check for `prepare` / `postinstall` scripts

### Python Strategy
- Priority order: uv.lock → poetry.lock → Pipfile.lock → requirements.txt → pyproject.toml → setup.py
- If uv.lock: `uv sync`
- If poetry.lock: `poetry install`
- If Pipfile.lock: `pipenv install`
- If requirements.txt: detect if uv available → `uv pip install -r requirements.txt` else `pip install -r requirements.txt`
- If pyproject.toml (no lock): try `uv sync`, fall back to `pip install -e .`
- Create virtualenv if needed

### Go Strategy
- `go mod download` then `go build ./...`

### Rust Strategy
- `cargo build`

### Docker Strategy
- If docker-compose.yml exists: `docker compose up -d` (only with --docker flag, since this is heavier)

### Make Strategy
- Look for common targets: `install`, `setup`, `dev`, `deps`, `dependencies`, `bootstrap`
- Run the first matching target

### Env Strategy
- Copy `.env.example` → `.env` (if .env doesn't already exist)
- Same for `.env.sample`, `.env.template`

## Execution Order
1. Env files (copy templates)
2. Language-specific dependency installation (npm/pip/etc)
3. Build steps (if detected)
4. Makefile targets (if not already covered)
5. Docker (only with --docker)

## Security (simplified)
- Never run `sudo` anything
- Never run `curl | sh` or `wget | bash`
- Only run known commands from a hardcoded allowlist
- If --ai mode produces unknown commands, show them but don't auto-execute
- Never read or transmit .env file contents

## Output Style
```
🔍 Detected: Node.js (npm), Python (uv)

📋 Plan:
  1. Copy .env.example → .env
  2. npm ci
  3. uv sync

🚀 Running...
  ✓ Copied .env.example → .env
  ✓ npm ci (3.2s)
  ✓ uv sync (1.1s)

✅ Project ready! (4.3s total)
```

## Dependencies
- typer >= 0.15.0
- rich >= 13.0.0
- pydantic >= 2.0.0
- (optional) ollama for --ai mode
