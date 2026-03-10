# Firehose CLI — Specification

## Overview

Firehose is a CLI tool that programmatically flattens a codebase into a single, token-optimized text file, prepends an analysis prompt, fans the payload out to multiple LLMs via OpenRouter in parallel, and collects/compares the resulting reports.

It is designed to be invoked by coding agents (Claude Code, Codex CLI, Gemini CLI, etc.) but also usable directly by humans. The flattening is deterministic and AST-aware by default, with an agent-editable manifest that provides full visibility and control over how the codebase is sequenced.

## Design Principles

- **Deterministic by default, agent-steerable when needed.** The CLI does all heavy lifting (scanning, parsing, sequencing) automatically. Agents inspect and override via the manifest — they never touch raw code parsing.
- **No tool calls, no agentic loops at inference time.** The model receives a single massive prompt (analysis prompt + flattened codebase) and returns a single response. Pure inference in, report out.
- **Structured capture.** Every run produces timestamped artifacts: the flat file, the prompt, each model's raw response, parsed reports, cost/token metadata, and a cross-model comparison.
- **Language agnostic.** Tree-sitter grammars where available, regex-based import resolution as fallback, extension heuristics as last resort.

## Stack

- **Python 3.12+** with `uv` for project management
- **Typer** — CLI framework
- **Pydantic v2** — all schemas (manifest, config, responses, reports)
- **openai** (AsyncOpenAI) — OpenRouter API calls (OpenAI-compatible)
- **httpx** — async HTTP for OpenRouter generation stats endpoint
- **tree-sitter** + language grammars — AST parsing for comment stripping, import resolution, dependency graphs
- **tiktoken** — token count estimation for metadata
- **Rich** — terminal UI (progress bars, live tables, status displays)
- **PyYAML** — manifest config serialization

## Project Structure

```
firehose/
├── pyproject.toml
├── README.md
├── src/
│   └── firehose/
│       ├── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   └── app.py              # Typer app, subcommands
│       ├── core/
│       │   ├── __init__.py
│       │   ├── scanner.py          # Codebase discovery, language detection
│       │   ├── flattener.py        # AST-aware flattening, comment stripping
│       │   ├── sequencer.py        # Dependency graph, topological sort
│       │   ├── prompter.py         # Analysis prompt construction
│       │   ├── router.py           # OpenRouter fan-out, async dispatch
│       │   ├── reporter.py         # Response capture, cross-model convergence analysis
│       │   └── tokenizer.py        # Token estimation utilities
│       ├── models/
│       │   ├── __init__.py
│       │   ├── manifest.py         # Manifest/config pydantic models
│       │   ├── response.py         # Model response schemas
│       │   └── report.py           # Analysis report schemas
│       └── config/
│           ├── __init__.py
│           ├── settings.py         # Global settings, env vars
│           └── prompts/
│               └── analyze.md      # Default analysis prompt template
└── tests/
```

## CLI Subcommands

### `firehose scan <root>`

Scans the codebase at `<root>` and generates `.firehose/manifest.yaml`.

**What it does:**
1. Walk the file tree, ignore non-code assets (images, binaries, lockfiles, node_modules, .git, etc.)
2. Detect language per file (tree-sitter grammar probe → extension fallback)
3. Identify entrypoints (main files, index files, manifest-declared entries like `package.json#main`)
4. Build dependency graph via AST-parsed imports (tree-sitter) or regex fallback
5. Detect unreachable files (not imported by anything reachable from entrypoints)
6. Compute per-file token estimates and character counts
7. Propose a hierarchical sequence (topological sort from entrypoints outward)
8. Write `.firehose/manifest.yaml`

**Output:** `.firehose/manifest.yaml` (see Manifest Schema below)

**Flags:**
- `--root <path>` — codebase root (default: `.`)
- `--output <path>` — manifest output path (default: `.firehose/manifest.yaml`)
- `--include <glob>` — additional include patterns
- `--exclude <glob>` — additional exclude patterns

---

### `firehose flatten`

Reads the manifest and produces the flat text file.

**What it does:**
1. Load `.firehose/manifest.yaml` (or `--manifest <path>`)
2. Resolve the hierarchical sequence tree depth-first
3. For each file: strip comments (AST-aware), collapse whitespace per config, resolve globs
4. Concatenate with file boundary markers and per-file metadata headers
5. Prepend codebase-level metadata header (file tree, language breakdown, total tokens, etc.)
6. Optionally prepend quarantined documentation section
7. Write to `.firehose/snapshots/<timestamp>/flat.txt`

**Output:** Flat text file (see Flat File Format below)

**Flags:**
- `--manifest <path>` — manifest path (default: `.firehose/manifest.yaml`)
- `--output <path>` — override output path
- `--strip-comments` / `--no-strip-comments` — override manifest setting
- `--include-docs` / `--no-include-docs` — override doc inclusion

---

### `firehose fire`

Sends the flat file payload to multiple models via OpenRouter.

**What it does:**
1. Load the flat file from the most recent snapshot (or `--snapshot <path>`)
2. Load or generate the analysis prompt (from config or `--prompt <path>`)
3. Combine prompt + flat file into payload
4. Fan out to N models concurrently via AsyncOpenAI (OpenRouter endpoint)
5. Display live Rich progress table: model name, status (pending/streaming/complete/failed), token count, latency, cost
6. For each completed response: save raw JSON, extract report, poll `/api/v1/generation?id=$ID` for actual cost/token stats
7. Write all response artifacts to the snapshot directory

**Output:** Per-model response JSONs and report markdown files in `.firehose/snapshots/<timestamp>/responses/` and `reports/`

**Flags:**
- `--models <comma-separated>` — model identifiers (e.g. `anthropic/claude-opus-4-6,openai/gpt-5.4,google/gemini-3.1-pro`)
- `--snapshot <path>` — snapshot directory to use (default: most recent)
- `--prompt <path>` — custom analysis prompt file
- `--max-concurrent <n>` — concurrency limit (default: 5)
- `--timeout <seconds>` — per-model timeout (default: 600, these are big jobs)
- `--max-tokens <n>` — output token budget per model (default: 16384)
- `--reasoning-effort <level>` — `high` or `xhigh`, passed to models that support it (default: high)
- `--response-format json` — opt-in structured JSON output (default: markdown, unstructured)

---

### `firehose report`

Synthesizes and compares model responses from a completed run.

**What it does:**
1. Load all report markdown files from a snapshot
2. Identify convergence: concerns raised independently by multiple models (high-confidence findings)
3. Identify divergence: areas where models disagree or focus on different things (flagged for human attention)
4. Surface unique observations: insights only one model caught
5. Generate a unified comparison report
6. Write to `.firehose/snapshots/<timestamp>/comparison.md`

The comparison step is itself an LLM call — it sends all model reports to a synthesis model and asks it to identify patterns of agreement and disagreement without editorializing. This costs one additional inference call but produces much better synthesis than keyword matching.

**Output:** `comparison.md` in the snapshot directory

**Flags:**
- `--snapshot <path>` — snapshot to analyze (default: most recent)
- `--synthesis-model <model>` — model used for comparison synthesis (default: first model from the run)
- `--format <md|json>` — output format (default: md)

---

### `firehose analyze <root>`

Full pipeline: scan → flatten → fire → report.

**What it does:** Runs all four stages sequentially with sensible defaults. The one-liner for humans and agents that just want results.

**Flags:** Accepts all flags from all subcommands. Key ones:
- `--models <comma-separated>` — **required** (no default model set)
- `--root <path>` — codebase root (default: `.`)
- `--prompt <path>` — analysis prompt override
- `--include-docs` / `--no-include-docs`

---

### `firehose instruct`

Prints agent-ready instructions to stdout. This is the "prompt executable" — instead of a magic markdown file, it's a CLI command that emits the instructions an agent needs to use Firehose effectively with the current codebase.

**What it does:**
1. Detects codebase context (root, size, languages if a manifest already exists)
2. Emits a structured instruction block that tells an agent:
   - What Firehose is and what it does
   - The exact CLI commands available and their order of operations
   - How to read and edit the manifest (what fields mean, what to change)
   - How to review the scan output and make sequencing decisions
   - How to trigger the fire and read the comparison report
   - Common overrides and flags worth knowing
3. Output is designed to be piped directly into an agent's context or copied into a system prompt

**Usage patterns:**
```bash
# Agent reads instructions at the start of a session
firehose instruct

# Pipe into clipboard for pasting into agent context
firehose instruct | pbcopy

# Agent can self-bootstrap
$(firehose instruct) # conceptually — agent reads this, then acts

# Scoped to a specific root
firehose instruct --root ./src

# Include manifest context if one already exists
firehose instruct --with-manifest
```

**Flags:**
- `--root <path>` — codebase root for context-aware instructions (default: `.`)
- `--with-manifest` — if `.firehose/manifest.yaml` exists, include a summary of it in the instructions so the agent has immediate context
- `--compact` — shorter version for agents with limited context budgets

The output is static text, not interactive. The agent reads it, understands the workflow, and then executes Firehose commands on its own.

---

### `firehose models`

Lists available models from OpenRouter.

**What it does:** Fetches and caches the OpenRouter model catalog, displays as a filterable table.

**Flags:**
- `--filter <query>` — filter by name/provider
- `--sort <field>` — sort by: `price`, `context`, `name`
- `--refresh` — bypass cache

---

### `firehose init`

Initializes a `.firehose/` directory with default config.

**What it does:** Creates `.firehose/config.yaml` with default settings (default models, prompt template, exclusion patterns, strip settings).

## Manifest Schema (`.firehose/manifest.yaml`)

The manifest is auto-generated by `scan` and editable by agents. It is both a report of what was found and the config for how flattening will proceed.

```yaml
version: 1
generated: "2026-03-09T14:32:00Z"
root: ./src

# Codebase-level metadata (populated by scan, read-only informational)
meta:
  total_files: 47
  total_tokens_est: 38400
  total_chars: 142618
  languages:
    typescript: { files: 38, tokens: 31200 }
    python: { files: 6, tokens: 5800 }
    yaml: { files: 3, tokens: 1400 }
  entrypoints_detected:
    - src/main.ts
    - src/server.ts
  unreachable_files:
    - src/deprecated/old-handler.ts

# Exclusion patterns
exclude:
  - "**/*.test.*"
  - "**/*.spec.*"
  - "**/fixtures/**"
  - "**/node_modules/**"
  - "**/.git/**"
  - "**/dist/**"
  - "**/build/**"
  - "**/*.lock"
  - "**/*.map"

# Stripping configuration
strip:
  comments: true
  whitespace: aggressive    # aggressive | moderate | none
  imports: false            # keep imports for model context

# Documentation inclusion
docs:
  include: true
  trust_level: unverified   # unverified | trusted
  files:
    - README.md
    - docs/architecture.md
  exclude:
    - docs/changelog.md
    - docs/contributing.md
    - LICENSE

# Hierarchical sequence tree
# Each node is either a file/glob (leaf) or a named group (branch)
# Groups can nest arbitrarily deep
sequence:
  - name: entrypoints
    order: manual             # manual | dependency | alphabetical
    children:
      - path: src/main.ts
      - path: src/server.ts

  - name: core
    order: dependency
    children:
      - path: src/router.ts
      - path: src/middleware.ts
      - name: auth
        order: manual
        children:
          - path: src/auth/session.ts
          - path: src/auth/oauth.ts
          - path: src/auth/permissions.ts
      - name: data-layer
        order: dependency
        children:
          - path: src/db/connection.ts
          - path: "src/db/models/*.ts"
          - path: "src/db/queries/*.ts"

  - name: services
    order: alphabetical
    children:
      - name: billing
        order: dependency
        children:
          - path: src/services/billing/stripe.ts
          - path: src/services/billing/invoices.ts
      - name: notifications
        order: manual
        children:
          - path: src/services/notifications/email.ts
          - path: src/services/notifications/sms.ts

  - name: utils
    order: alphabetical
    collapse: true            # minimal separators between files in this group
    children:
      - path: "src/utils/*.ts"

# Output configuration
output:
  separator: "--- {filepath} [tokens: ~{tokens}, chars: {chars}, lang: {lang}] ---"
  file_tree: true             # include file tree in header
  metadata_header: true       # include codebase metadata block
```

## Pydantic Models

### Manifest Node (recursive)

```python
from pydantic import BaseModel
from typing import Literal

class SequenceNode(BaseModel):
    # Leaf (file)
    path: str | None = None

    # Branch (group)
    name: str | None = None
    order: Literal["dependency", "manual", "alphabetical"] = "dependency"
    collapse: bool = False
    children: list["SequenceNode"] = []

    def is_leaf(self) -> bool:
        return self.path is not None

    def is_group(self) -> bool:
        return self.name is not None and len(self.children) > 0
```

### Model Response

```python
class ModelResponse(BaseModel):
    model: str                          # e.g. "anthropic/claude-opus-4-6"
    provider: str                       # e.g. "anthropic"
    status: Literal["complete", "failed", "timeout"]
    latency_ms: int
    tokens_prompt: int
    tokens_completion: int
    cost_usd: float
    finish_reason: str
    generation_id: str
    raw_response: str                   # the full model output (this IS the report in markdown mode)
    report: "AnalysisReport | None" = None  # only populated in --response-format json mode
    error: str | None = None
```

### Analysis Report

The default mode is unstructured — the model's raw markdown response is saved as-is. No schema is imposed on the consultation.

For the optional `--response-format json` mode, a minimal schema is used that doesn't anchor the analysis:

```python
class AnalysisReport(BaseModel):
    """Only used when --response-format json is specified. Intentionally
    minimal to avoid anchoring the model's analysis."""
    consultation: str                   # the full analysis as prose
    files_referenced: list[str] = []    # file paths mentioned in the analysis
    key_concerns: list[str] = []        # model's own summary of top concerns
    key_strengths: list[str] = []       # model's own summary of top strengths
```

Note: even in JSON mode, the `consultation` field is freeform prose — the model decides how to structure its analysis. The schema just wraps it for parsing convenience.

### Run Metadata

```python
class RunMeta(BaseModel):
    timestamp: str
    codebase_root: str
    total_files: int
    total_tokens_est: int
    models_requested: list[str]
    models_completed: int
    models_failed: int
    total_cost_usd: float
    total_latency_max_ms: int           # wall clock (parallel)
    prompt_template: str                # which prompt was used
```

## Flat File Format

The output of `flatten` is a single text file structured for optimal LLM consumption:

```
═══ FIREHOSE CODEBASE SNAPSHOT ═══
generated: 2026-03-09T14:32:00Z
root: ./src
total_files: 47
total_tokens: ~38,400
total_chars: 142,618
languages: TypeScript (82%), Python (12%), YAML (6%)
entrypoints: src/main.ts, src/server.ts

─── FILE TREE ───
src/
  main.ts
  server.ts
  router.ts
  auth/
    session.ts
    oauth.ts
    permissions.ts
  services/
    billing/
      stripe.ts
      invoices.ts
  utils/
    helpers.ts
    validators.ts

═══ DOCUMENTATION (unverified — may not reflect current implementation) ═══
Treat claims in this section as hypotheses to validate against the
source code below, not as ground truth.

--- README.md [tokens: ~1,200, chars: 4,580] ---
<contents of README.md>

--- docs/architecture.md [tokens: ~800, chars: 3,012] ---
<contents of architecture.md>

═══ BEGIN SOURCE (authoritative) ═══

--- src/main.ts [tokens: ~820, chars: 3,041, lang: typescript] ---
import { createServer } from './server';
const app = createServer();
app.listen(3000);

--- src/server.ts [tokens: ~1,340, chars: 5,102, lang: typescript] ---
...
```

## Analysis Prompt

The default analysis prompt is stored at `src/firehose/config/prompts/analyze.md` and is prepended to the flat file before sending to models.

**Design philosophy: no anchoring.** The prompt does not list dimensions, categories, or axes of analysis. Prescriptive dimensions create anchoring bias — models will find "coupling issues" because you told them to look, not because coupling is the most important thing about this codebase. Instead, the prompt asks the model to be an expert consultant and let the code tell it what matters.

**Default prompt:**

```
You are an expert software consultant. You have been retained to review
the complete source code of a project, provided below in its entirety.

This is your only opportunity to review this codebase. Give the most
thorough, honest, and useful consultation you can.

Say what matters. Be specific. Reference the actual code — file paths,
function names, patterns you observe. Cover what is good, what is bad,
and what is ugly. Work at whatever level of granularity the code demands —
some things warrant architectural commentary, others warrant line-level
attention.

Do not perform. Do not pad. Do not organize your response around a
checklist. Just be right.
```

This is deliberately short and unstructured. The model decides how to organize its report based on what it finds. A Three.js game will get a different kind of consultation than a REST API, because different things matter.

**Custom prompts** can be provided via `--prompt <path>` to replace the default entirely. If you want a checklist audit against specific dimensions, write that prompt — but it's not the default behavior.

**Response format:** Default is unstructured markdown (`--response-format markdown`). The model writes whatever report it thinks is best. Structured JSON (`--response-format json`) is available as an opt-in for when you want machine-parseable output, but it constrains the model's analysis and is not recommended for general use.

**Comparison implications:** Without a shared schema, the comparison step (`firehose report`) can't do field-by-field diffing across models. Instead, it works by surfacing convergence and divergence — where multiple models independently raise the same concern (without being prompted to), that's a high-confidence finding. Where they disagree or focus on different things, that's flagged for human attention.

## OpenRouter Integration

### Authentication

API key via environment variable `OPENROUTER_API_KEY` or `.firehose/config.yaml`.

### Client Setup

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
    default_headers={
        "HTTP-Referer": "https://github.com/user/firehose",
        "X-Title": "Firehose CLI"
    }
)
```

### Fan-out

```python
async def fire_model(client, model: str, payload: str, sem: asyncio.Semaphore):
    async with sem:
        t0 = time.monotonic()
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": payload}],
            max_tokens=16384,
            extra_body={"reasoning_effort": "high"},
        )
        latency = int((time.monotonic() - t0) * 1000)
        return model, response, latency

async def fire_all(models: list[str], payload: str, max_concurrent: int = 5):
    sem = asyncio.Semaphore(max_concurrent)
    tasks = [fire_model(client, m, payload, sem) for m in models]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

### Cost Tracking

After each completion, poll the generation stats endpoint:

```python
async def get_generation_stats(gen_id: str) -> dict:
    resp = await httpx_client.get(
        f"https://openrouter.ai/api/v1/generation?id={gen_id}",
        headers={"Authorization": f"Bearer {api_key}"}
    )
    return resp.json()["data"]
```

## Snapshot Directory Structure

Each run creates a timestamped snapshot:

```
.firehose/
├── config.yaml                         # global config (default models, API key ref, etc.)
├── manifest.yaml                       # current flattening manifest
└── snapshots/
    └── 2026-03-09T143200/
        ├── meta.json                   # run metadata
        ├── flat.txt                    # flattened codebase
        ├── prompt.md                   # analysis prompt used
        ├── payload.txt                 # prompt + flat (what was sent)
        ├── responses/
        │   ├── anthropic--claude-opus-4-6.json
        │   ├── openai--gpt-5.4.json
        │   ├── google--gemini-3.1-pro.json
        │   └── deepseek--deepseek-r1.json
        ├── reports/
        │   ├── anthropic--claude-opus-4-6.md
        │   ├── openai--gpt-5.4.md
        │   ├── google--gemini-3.1-pro.md
        │   └── deepseek--deepseek-r1.md
        └── comparison.md              # cross-model synthesis
```

## Target Model Tier

Firehose targets frontier-class models only. The whole point is to throw a full codebase at the most capable models available and get deep analysis back. Small models can't hold the context, can't reason deeply enough, and produce shallow reports that aren't worth comparing.

**Current landscape (March 2026):**

| Model | Context Window | Notes |
|-------|---------------|-------|
| Claude Opus 4.6 | 1M tokens | Anthropic's most capable |
| Claude Sonnet 4.6 | 1M tokens | Strong reasoning, lower cost |
| GPT-5.4 Thinking | 1.05M tokens | OpenAI's frontier reasoning model |
| GPT-5.4 Pro | 1.05M tokens | Max performance variant |
| Gemini 3.1 Pro | 1M tokens | Google's frontier, 64K output cap |
| Gemini 3 Flash | 1M tokens | Faster/cheaper, still capable |
| DeepSeek R1 | 128K tokens | Open-source reasoning (limited context) |

All major frontier models now support ~1M token context windows. A typical 50K-line codebase flattened with comments stripped will land around 150K-300K tokens — well within budget for all targets. Even large monorepos at 500K+ tokens fit comfortably.

**Thinking and output budgets should be high.** These models are doing deep analysis, not chat. We want them to think hard and write thorough reports. Config should expose:
- `reasoning_effort` — maps to OpenRouter/provider reasoning params (`high`, `xhigh` where supported)
- `max_tokens` — output budget, default 16384 (generous reports, not chat-length responses)

Models that don't support a given parameter simply ignore it (OpenRouter handles this).

## Configuration (`.firehose/config.yaml`)

```yaml
openrouter:
  api_key_env: OPENROUTER_API_KEY      # env var name, never store key directly

defaults:
  models:
    - anthropic/claude-opus-4-6
    - openai/gpt-5.4
    - google/gemini-3.1-pro
  max_concurrent: 5
  timeout_seconds: 600                  # long timeout — these are big jobs
  response_format: markdown              # markdown | json (markdown recommended — no anchoring)
  max_tokens: 16384                     # high output budget for thorough reports
  reasoning_effort: high                # high | xhigh (passed to models that support it)

prompts:
  default: analyze                      # references prompts/analyze.md
  custom: []                            # user-defined prompt paths

scan:
  default_exclude:
    - "**/*.test.*"
    - "**/*.spec.*"
    - "**/node_modules/**"
    - "**/.git/**"
    - "**/dist/**"
    - "**/build/**"
    - "**/*.lock"
    - "**/*.map"
    - "**/__pycache__/**"
    - "**/.venv/**"
```

## Agent Integration

Agents interact with Firehose through the CLI. The `instruct` command bootstraps the agent with everything it needs to know.

A typical agent workflow:

```bash
# 0. Agent gets its instructions (can be piped into agent context at session start)
firehose instruct --root ./src

# 1. Agent scans the codebase — gets the manifest
firehose scan ./src

# 2. Agent reads the manifest to understand what Firehose found
cat .firehose/manifest.yaml

# 3. Agent edits the manifest (reorder, exclude, regroup)
# ... agent writes changes to .firehose/manifest.yaml ...

# 4. Agent triggers flattening with the curated manifest
firehose flatten

# 5. Agent fires to models (high reasoning effort, generous output budget)
firehose fire --models anthropic/claude-opus-4-6,openai/gpt-5.4,google/gemini-3.1-pro

# 6. Agent reads the comparison report
cat .firehose/snapshots/latest/comparison.md
```

The `latest` symlink always points to the most recent snapshot for convenience.

For fully automated runs (human or agent that doesn't need to curate):
```bash
firehose analyze ./src --models anthropic/claude-opus-4-6,openai/gpt-5.4
```

## Out of Scope (v1)

- Web UI / dashboard
- FastAPI service mode (future consideration — core is structured to support it later)
- Custom tree-sitter grammar installation (v1 ships with common languages)
- Prompt versioning / A-B testing
- Integration with eval harnesses (promptfoo, deepeval, etc.)
- Git-aware diffing (only flatten changed files)
- Chunk/split for codebases exceeding model context windows (v1 warns and skips)

## Supported Languages (v1)

Tree-sitter grammars (full AST support — comment stripping, import resolution):
- TypeScript / JavaScript
- Python
- Rust
- Go
- Java
- C / C++

Regex fallback (import pattern matching only, basic comment stripping):
- Ruby, PHP, Swift, Kotlin, C#, Scala

Extension-only (no parsing, included as raw text with whitespace collapse):
- Everything else

## Open Questions

1. **Comparison algorithm for unstructured reports?** Without a shared schema, `firehose report` needs to do semantic comparison — identify where models converge/diverge on concerns without structured fields to diff. Options: (a) use another model call to synthesize the comparison, (b) basic text similarity / keyword extraction, (c) just concatenate all reports side-by-side and let the human/agent read them. Leaning toward (a) — use one of the same frontier models to read all reports and produce a synthesis.
2. **Snapshot retention?** Auto-prune old snapshots? Keep N most recent? Or leave it to the user/agent?
3. **`.firehose/` in `.gitignore`?** The manifest probably should be committed (it's the curated flattening plan). Snapshots and config with API key refs probably shouldn't. `firehose init` should generate a `.gitignore` inside `.firehose/`.
4. **Context overflow strategy?** All target models are 1M+ now, so this is unlikely for most codebases. But for massive monorepos that exceed 1M tokens flattened: should Firehose warn and skip that model, auto-truncate the least important groups, or split into multiple passes? Leaning toward warn-and-skip for v1.
5. **`firehose instruct` versioning?** As the CLI evolves, the instructions it emits need to stay in sync. Should the instructions template be a file that gets updated with the code, or generated dynamically from the actual Typer command definitions?
