# Foxhound

Sniff out ideas worth building. Ship them fast.

Foxhound is a product discovery engine that scans engineering signals, finds opportunities, creates work items, and builds improvements with your approval. It's a Python CLI distributed via PyPI.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

## Installation

### From source (development)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/your-org/foxhound.git
cd foxhound
uv sync --dev
```

### Production install (without dev dependencies)

```bash
uv sync
```

### Optional extras

SMS and email notifications have optional dependencies:

```bash
uv sync --dev --extra sms --extra email
```

### Global install (use `foxhound` from anywhere)

```bash
uv tool install -e .
```

This puts `foxhound` on your PATH — no `uv run` or venv activation needed.

## Configuration

Create a `foxhound.yaml` in your project root:

```yaml
models:
  provider: anthropic
  api_key_env: ANTHROPIC_API_KEY
  tiers:
    reasoning: claude-opus-4.6
    balanced: claude-sonnet-4.6
    fast: claude-haiku-4.5
notifications:
  enabled: true
  channels:
    desktop:
      enabled: true
    email:
      enabled: false
      api_key_env: RESEND_API_KEY
      to_address_env: USER_EMAIL
    sms:
      enabled: false
      account_sid_env: TWILIO_ACCOUNT_SID
      auth_token_env: TWILIO_AUTH_TOKEN
      from_number_env: TWILIO_FROM_NUMBER
      to_number_env: USER_PHONE_NUMBER
    slack:
      enabled: false
      webhook_env: SLACK_WEBHOOK_URL
    discord:
      enabled: false
      webhook_env: DISCORD_WEBHOOK_URL
    web_push:
      enabled: true
```

Store your API key securely:

```bash
foxhound secret set ANTHROPIC_API_KEY
```

Or set it as an environment variable:

```bash
export ANTHROPIC_API_KEY="your-key"
```

Then initialize foxhound in your repo:

```bash
foxhound init
```

## How It Works

Foxhound operates as a pipeline: discover opportunities, approve them, execute in isolation, review the output, and promote the results.

### 1. Discover

Two discovery modes feed the pipeline:

- **Repo-native scanning** (`foxhound scan`) — Scanners analyze your repository for TODOs, dependency issues, and code quality signals. Each finding becomes a work item with risk level and confidence metadata.
- **External scouting** (`foxhound scout`) — Eight connectors pull signals from GitHub Trending, Reddit, HackerNews, Dev.to, Product Hunt, Lobsters, NewsAPI, and RSS feeds. Raw opportunities are scored on star velocity, improvability, buildability, and business value using configurable scoring profiles.

### 2. Approve

All discovered work items pass through a human review gate. Nothing executes without explicit approval. You can approve, edit, reject, or block any item.

### 3. Execute

Approved items are queued as jobs with a frozen configuration snapshot (config changes never affect in-flight work). Execution happens in isolated git worktrees — the main repo is never modified directly.

Every worker runs through the **harness contract**, a strict six-step lifecycle:

1. **validate_input** — Preflight checks on the task envelope
2. **build_context** — Assemble sanitized context with trust labels
3. **execute** — Run worker logic with model and tool access
4. **sanitize_output** — Strip dangerous patterns and redact secrets
5. **evaluate_output** — Run grounding, confidence, and safety checks
6. **finalize** — Emit structured results, artifacts, and events

### 4. Review

A code review worker is automatically spawned to evaluate generated patches. It produces a verdict: pass, pass with warnings, needs review, or recommend reject.

### 5. Promote

Passing results are promoted back to a branch and optionally opened as a pull request. All execution is recorded in the database with a full audit trail.

### Trust Boundaries

All content flowing through the system is classified into trust tiers:

| Tier         | Examples                               | Handling                               |
| ------------ | -------------------------------------- | -------------------------------------- |
| Trusted      | System instructions, approved recipes  | May influence execution                |
| Semi-trusted | Repo files, CI logs, issue metadata    | Evidence; must be sanitized            |
| Untrusted    | Reddit, articles, external web content | Evidence only; never execution control |

### Model Tiers

Foxhound references capability tiers, not model names. You map tiers to models in config:

| Tier        | Used For                                            |
| ----------- | --------------------------------------------------- |
| `reasoning` | Code review, complex builds, architecture decisions |
| `balanced`  | Standard execution, discovery, maintenance          |
| `fast`      | Scout scoring, simple fixes, style checks           |

## Scout Connectors

Eight connectors are available out of the box:

| Connector        | Source                          | Auth Required |
| ---------------- | ------------------------------- | ------------- |
| **GitHub**       | Trending repos, star velocity   | Optional      |
| **Reddit**       | Subreddit posts and discussions | Optional      |
| **HackerNews**   | Top stories, search, rankings   | No            |
| **Dev.to**       | Articles and discussions        | No            |
| **Product Hunt** | Product launches                | No            |
| **Lobsters**     | Curated tech news               | No            |
| **NewsAPI**      | News aggregation                | Yes           |
| **RSS**          | Any RSS/Atom feed               | No            |

### Scout API Keys

Most connectors work without API keys but with reduced capacity. Keys are optional and set via environment variables:

```bash
export GITHUB_TOKEN="ghp_..."            # GitHub personal access token
export REDDIT_CLIENT_ID="..."            # Reddit OAuth app client ID
export REDDIT_CLIENT_SECRET="..."        # Reddit OAuth app client secret
export NEWS_API_KEY="..."                # NewsAPI key (required for NewsAPI connector)
# HackerNews, Dev.to, Product Hunt, Lobsters, RSS require no credentials
```

### Without API keys

| Connector  | What works                                  | Limitation                                              |
| ---------- | ------------------------------------------- | ------------------------------------------------------- |
| GitHub     | Trending repo search, star counts, metadata | 60 requests/hour per IP — runs out fast during scanning |
| Reddit     | Public subreddit posts via JSON fallback    | Lower rate limits, no access to private subreddits      |
| HackerNews | Full access to all stories and search       | None — the API is completely public                     |

### With API keys

| Connector  | Improvement                                                       |
| ---------- | ----------------------------------------------------------------- |
| GitHub     | 5,000 requests/hour (83x increase)                                |
| Reddit     | Higher rate limits, more stable access, private subreddit support |
| HackerNews | No difference                                                     |

For light or occasional use, no keys are needed. For continuous scanning, GitHub and Reddit tokens are strongly recommended.

## Notifications

Foxhound proactively reaches out to you when it finds something worth your attention. After each scout cycle, high-scoring opportunities trigger notifications through your configured channels.

### Channels

| Channel      | Setup                         | Cost       |
| ------------ | ----------------------------- | ---------- |
| **Desktop**  | Works out of the box          | Free       |
| **Web Push** | Works when web UI is running  | Free       |
| **Slack**    | Create an incoming webhook    | Free       |
| **Discord**  | Create a server webhook       | Free       |
| **Email**    | Resend account (3k emails/mo) | Free tier  |
| **SMS**      | Twilio account                | Free trial |

### Storing credentials

Use the system keychain instead of environment variables:

```bash
# Model providers
foxhound secret set ANTHROPIC_API_KEY
foxhound secret set OPENAI_API_KEY
foxhound secret set GITHUB_TOKEN

# Notification channels
foxhound secret set RESEND_API_KEY
foxhound secret set TWILIO_ACCOUNT_SID
foxhound secret set TWILIO_AUTH_TOKEN
foxhound secret set SLACK_WEBHOOK_URL
foxhound secret set DISCORD_WEBHOOK_URL
```

Each command prompts for the value with hidden input and stores it securely in macOS Keychain, Linux Secret Service, or Windows Credential Manager.

### Configuration

`foxhound init` generates all notification options in `foxhound.yaml`. Desktop and web push are enabled by default. Enable additional channels and point them at your credentials:

```yaml
notifications:
  enabled: true
  channels:
    desktop:
      enabled: true
    email:
      enabled: true
      api_key_env: RESEND_API_KEY
      to_address_env: USER_EMAIL
    sms:
      enabled: true
      account_sid_env: TWILIO_ACCOUNT_SID
      auth_token_env: TWILIO_AUTH_TOKEN
      from_number_env: TWILIO_FROM_NUMBER
      to_number_env: USER_PHONE_NUMBER
    slack:
      enabled: false
      webhook_env: SLACK_WEBHOOK_URL
    discord:
      enabled: false
      webhook_env: DISCORD_WEBHOOK_URL
    web_push:
      enabled: true
```

### When notifications fire

- **High-score opportunity** — Scout finds something above your threshold
- **Build complete** — Success or failure
- **Approval required** — A background session needs your input
- **Trend spike** — 5+ opportunities in the same topic in one cycle
- **Security blocked** — A policy or security rule blocked an action

SMS is reserved for critical events only (score above 0.95, critical build failures) to avoid noise.

## Dashboard

Foxhound includes a terminal UI built on Textual. Launch it with:

```bash
foxhound dashboard
```

The dashboard provides views for work items, scout inbox, run history, repository management, diagnostics, and retention status — all navigable from a sidebar.

## Multi-Repo Support

Foxhound can manage multiple repositories from a single install:

```bash
foxhound repo add /path/to/project    # Register a repository
foxhound repo list                     # Show all registered repos
foxhound repo use <repo_id>           # Switch active repository context
```

## Model Providers

Foxhound supports multiple model providers. Each provider can be assigned to any capability tier.

| Provider      | Models                              | Auth              |
| ------------- | ----------------------------------- | ----------------- |
| **Anthropic** | Claude Opus, Sonnet, Haiku          | API key           |
| **OpenAI**    | GPT-4o, GPT-4o-mini, o1, etc.      | API key           |
| **DeepSeek**  | DeepSeek Chat, Coder                | API key           |
| **Google**    | Gemini Pro, Flash                   | API key           |
| **Local**     | Ollama, LM Studio, vLLM (any model)| None (local)      |

## Local Models

Foxhound supports local models (Ollama, LM Studio, vLLM) through any OpenAI-compatible endpoint. No API key required for local providers.

```yaml
models:
  providers:
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
    local:
      base_url: http://localhost:11434/v1
  tiers:
    reasoning: anthropic/claude-opus-4.6
    balanced: anthropic/claude-sonnet-4.6
    fast: local/qwen3-8b
```

This routes your `fast` tier (scout scoring, simple fixes) through a local model while keeping `reasoning` and `balanced` on Anthropic. You can assign any tier to any provider.

## Usage

Run these commands from the repository you want foxhound to operate on, not from the foxhound source directory:

```bash
cd your-project/

# Setup
foxhound init                  # Initialize foxhound in this repo
foxhound doctor                # Validate environment and configuration

# Discovery
foxhound scan                  # Run repo-native discovery scanners
foxhound scout                 # Run external opportunity discovery

# Workflow
foxhound approve <id>          # Approve/edit/reject a work item
foxhound run <id>              # Execute approved item
foxhound log                   # Show run history and work items
foxhound status                # Show current pipeline status
foxhound analyze               # Summarize failures and suggestions

# Dashboard
foxhound dashboard             # Open the TUI dashboard

# Multi-repo
foxhound repo add <path>       # Register a repository
foxhound repo list             # Show all registered repos
foxhound repo use <repo_id>   # Switch active repository context

# Secrets
foxhound secret set <key>      # Store a credential in the system keychain
foxhound secret get <key>      # Retrieve a stored credential
foxhound secret list           # List stored credential keys

# Maintenance
foxhound clear                 # Clear work items and runs
foxhound rebuild               # Rebuild database indexes
foxhound retention-status      # Show retention policy status
foxhound retention-prune       # Remove old artifacts
foxhound retention-compact     # Compact database
```

## Retention

Foxhound stores run history, artifacts, and event logs in a local SQLite database. Over time this grows. Built-in retention management keeps it in check:

```bash
foxhound retention-status      # See current DB size and artifact counts
foxhound retention-prune       # Remove artifacts older than the retention window
foxhound retention-compact     # Vacuum the database to reclaim disk space
```

## Running Tests

```bash
uv run pytest                          # Run all tests
uv run pytest tests/test_core.py       # Run specific test file
uv run pytest --cov=foxhound           # Run with coverage
```

## License

MIT
