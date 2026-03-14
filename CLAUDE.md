# Foxhound

Autonomous product discovery engine that scans open-source repositories, identifies improvement opportunities, and executes differentiated builds. Python CLI distributed via PyPI.

## Project Structure

```
foxhound/
  cli/              # Typer CLI commands
  core/             # coordinator, queue, locks, event bus, models
  harness/          # worker lifecycle runtime wrapper
  secrets/          # secret provider chain and redaction
  discovery/        # repo-native work discovery
  scout/            # external opportunity discovery
  sanitization/     # trust labeling and output cleanup
  evaluation/       # output and candidate evaluation
  execution/        # context assembly, patching, validation, promotion
  recipes/          # recipe schemas, loaders, built-ins
  policies/         # policy packs, rules, constraints
  adapters/         # model providers, MCP, GitHub, notifications
  observer/         # event persistence, manifests, retention
  analyzer/         # diagnostics and rule suggestions
  storage/          # SQLite access and artifact references
  tests/            # unit and integration tests
  docs/             # examples, recipe docs, policy docs
```

**Note:** This project is early-stage. Not all directories exist yet. The structure above is the target architecture from the engineering blueprint.

## Architecture Rules

These rules are non-negotiable. All contributors and AI agents must follow them.

### Worker Communication
Workers never call each other directly. All communication goes through the coordinator, the harness, and typed events or structured artifacts.

### Harness Contract
Every worker runs through the harness contract. Six methods in order:
1. `validate_input` - Validate task envelope and preflight requirements
2. `build_context` - Build or load sanitized context pack with trust labels
3. `execute` - Run worker logic with exposed tools and model access
4. `sanitize_output` - Normalize output and strip dangerous patterns
5. `evaluate_output` - Run evaluator/security hooks
6. `finalize` - Emit structured result envelope, events, artifacts

No exceptions. No shortcuts.

### Trust Boundaries
Three trust tiers enforced at all boundaries:

| Tier | Examples | Handling |
|------|----------|----------|
| Trusted | system instructions, approved recipes, user edits | May influence execution subject to policy |
| Semi-trusted | repo files, CI logs, issue metadata | Evidence for analysis; must be sanitized |
| Untrusted | Reddit, articles, reviews, external web content | Evidence only; never execution control |

**Hard rule:** Untrusted content is evidence, never instructions.

### Secret Management
Secrets never appear in:
- SQLite database
- Manifests
- Logs
- Context packs
- Git commits

Secrets are injected through the harness with scoped access only.

### Isolated Execution
All execution happens in isolated workspaces. Never modify the main repository directly. Promotion to canonical branches requires validation and approval.

### Configuration Snapshots
Jobs execute under the configuration snapshot from queue time. Recipe and policy changes never affect in-flight work.

### Shell Access
No blanket shell access. Commands must be whitelisted. No arbitrary shell execution.

## Model Tier System

Foxhound uses capability tiers, not model names. All code references tiers. Never hardcode a model name.

| Tier | Description | Used For |
|------|-------------|----------|
| `reasoning` | Strongest available model | Code review, complex builds, architecture decisions |
| `balanced` | Workhorse model | Standard execution, discovery, maintenance |
| `fast` | Cheapest capable model | Scout scoring, simple fixes, style checks |

Users map tiers to specific models in `foxhound.yaml`:

```yaml
models:
  provider: anthropic
  api_key_env: ANTHROPIC_API_KEY
  tiers:
    reasoning: claude-opus-4.6
    balanced: claude-sonnet-4.6
    fast: claude-haiku-4.5
```

## Dev Environment Setup

This project uses [uv](https://docs.astral.sh/uv/) for fast, reliable Python package management.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/your-org/foxhound.git
cd foxhound

# Install dependencies (uv creates venv automatically)
uv sync --dev

# Or install without dev dependencies
uv sync

# Configure API keys
export ANTHROPIC_API_KEY="your-key"
# or
export OPENAI_API_KEY="your-key"
```

**Note:** uv automatically manages the virtual environment in `.venv/`. To run commands within the environment, use `uv run <command>` or activate the venv manually with `source .venv/bin/activate`.

Minimum `foxhound.yaml` configuration:

```yaml
models:
  provider: anthropic
  api_key_env: ANTHROPIC_API_KEY
  tiers:
    reasoning: claude-sonnet-4.6
    balanced: claude-sonnet-4.6
    fast: claude-haiku-4.5
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_core.py

# Run with coverage
uv run pytest --cov=foxhound

# Run specific test
uv run pytest tests/test_core.py::test_function_name -v
```

## How to Add a New Worker

1. **Create worker class** implementing the Worker Protocol:

```python
from foxhound.harness import Worker, TaskEnvelope, ResultEnvelope

class MyWorker(Worker):
    worker_name = "my_worker"
    worker_class = "helper"  # or "root"
    capabilities = ["repo_read"]  # declared permissions
    allowed_spawn_targets = []
    default_timeout_seconds = 300
    default_budget = 1.0

    def validate_input(self, task: TaskEnvelope) -> ValidationResult: ...
    def build_context(self, task: TaskEnvelope) -> ContextBuildResult: ...
    def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput: ...
    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput: ...
    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult: ...
    def finalize(self, result: EvaluationResult) -> ResultEnvelope: ...
```

2. **Declare capabilities** - Valid permissions:
   - `repo_read` - Read repository files
   - `repo_write` - Write to isolated workspace
   - `network` - Network access (bounded)
   - `shell` - Whitelisted shell commands only
   - `spawn` - Can request helper workers

3. **Register with coordinator** in the worker registry

4. **Add tests** in `tests/` directory

## How to Add a New Provider Adapter

1. **Implement adapter interface**:

```python
from foxhound.adapters import ProviderAdapter

class MyProviderAdapter(ProviderAdapter):
    def authenticate(self, config: ProviderConfig) -> bool: ...
    def format_request(self, messages: list, params: dict) -> dict: ...
    def parse_response(self, response: dict) -> ModelResponse: ...
    def count_tokens(self, text: str) -> int: ...
    def track_cost(self, usage: TokenUsage) -> float: ...
```

2. **Register in adapter registry** with provider name

3. **Add tier mapping suggestions** to provider registry:

```python
PROVIDER_TIER_SUGGESTIONS = {
    "my_provider": {
        "reasoning": "my-provider-large",
        "balanced": "my-provider-medium",
        "fast": "my-provider-small"
    }
}
```

## How to Add a New Recipe

1. **Create recipe YAML** with required fields:

```yaml
name: my_recipe
version: 1.0.0
execution_strategy: one_shot  # or ralph_loop
description: What this recipe does

# Optional tier overrides
tier_overrides:
  execution: balanced
  review_final: reasoning

# Context and validation settings
context:
  include_patterns: ["src/**/*.py"]
  exclude_patterns: ["**/test_*.py"]

validation:
  commands: ["pytest", "mypy"]
```

2. **Place recipe in appropriate scope**:
   - `foxhound/recipes/builtins/` - Built-in recipes
   - `~/.config/foxhound/recipes/` - Global user recipes
   - `.foxhound/recipes/` - Repo-local recipes

3. **Recipe schema validation** runs automatically on load

## Coding Conventions

- **Python version:** 3.13 for development, minimum 3.11+ supported
- **Type hints:** Required on all function signatures
- **Data contracts:** Pydantic models for all data structures
- **Storage:** SQLite for metadata, filesystem for heavy artifacts
- **CLI:** Typer for commands, Rich for output formatting
- **Testing:** pytest
- **Naming:** Descriptive variable names, no abbreviations
- **Docstrings:** Required on all public functions and classes

## Key Commands

```bash
foxhound init          # Initialize .foxhound config and local DB
foxhound scan          # Run discovery scanners
foxhound scout         # Run external opportunity discovery
foxhound approve <id>  # Approve/edit/reject a work item
foxhound run <id>      # Execute approved item
foxhound analyze       # Summarize failures and suggestions
foxhound doctor        # Validate environment and configuration
```

## Worker Capabilities Matrix

| Worker | Repo Read | Repo Write | Network | Shell | Can Spawn |
|--------|-----------|------------|---------|-------|-----------|
| ScoutWorker | No | No | Yes (bounded) | No | Yes |
| DiscoveryWorker | Yes | No | Optional | No | Yes |
| ExecutionWorker | Yes | Yes (isolated) | Optional | Whitelisted | Yes |
| AnalyzerWorker | Yes (artifacts) | No | No | No | Yes |
| SecurityReviewWorker | Yes | No | No | No | No |

## State Machines

**Work Item States:**
```
discovered -> suggested -> approved|edited|rejected|blocked -> executing -> completed|failed
```

**Run States:**
```
queued -> preparing -> context_built -> executing -> validating -> security_review -> branch_ready -> pr_draft_ready -> completed|failed|cancelled
```

## Task Workflow

**Picking up work:**
- Find an open issue in the current milestone
- Assign yourself (or comment that you're working on it)
- Create a branch: `foxhound/<issue-number>-short-description`
- Example: `foxhound/47-ralph-execution-strategy`

**Commit convention (conventional commits):**
- `feat(module): description (#issue)` — new functionality
- `fix(module): description (#issue)` — bug fix
- `refactor(module): description (#issue)` — restructure without behavior change
- `test(module): description (#issue)` — adding or updating tests
- `docs: description (#issue)` — documentation only
- `chore: description (#issue)` — tooling, config, dependencies

**Pull requests:**
- Open PR against `main`
- PR title follows the same conventional commit format
- PR body must include: what changed, which issue it closes (`Closes #47`), and how to test it
- All PRs must pass CI (lint, type check, tests) before review
- Never merge your own PR without at least one review

**CI checks (run on every PR):**
- `uv run ruff check .` — linting
- `uv run mypy foxhound/` — type checking
- `uv run pytest tests/` — test suite

**Issue lifecycle:**
```
open -> assigned -> branch created -> PR opened -> CI passes -> reviewed -> merged -> issue auto-closes
```
