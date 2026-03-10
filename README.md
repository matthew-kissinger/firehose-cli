# Firehose CLI

Multi-model codebase analysis. Flatten a project into a single file, fan it out to frontier LLMs via [OpenRouter](https://openrouter.ai) in parallel, and cross-reference their reports.

Three models independently review your code. Where they agree, that's a high-confidence finding. Where they diverge, that's flagged for human attention.

## Install

Requires Python 3.12+.

```bash
# Recommended: install globally
uv tool install firehose-cli
# or
pipx install firehose-cli
```

Then store your API key once:

```bash
firehose auth
# Paste your OpenRouter key when prompted
# Stored in ~/.config/firehose/credentials (600 perms)
```

That's it. `firehose` is now available from any directory.

> Already have `OPENROUTER_API_KEY` in your environment? That works too - env vars take precedence over stored credentials.

## Quick start

```bash
# Full pipeline in one command
firehose analyze ./src --models anthropic/claude-opus-4.6,openai/gpt-5.4,google/gemini-3.1-pro-preview

# Or step by step for more control
firehose scan ./src --exclude 'vendor' --exclude 'examples' --exclude '*.test.*'
# Edit .firehose/manifest.yaml - reorder, remove, regroup
firehose flatten
firehose fire --models anthropic/claude-opus-4.6,openai/gpt-5.4,google/gemini-3.1-pro-preview
firehose report
```

## How it works

```
         your codebase
              |
         [1. scan]         discover files, detect languages, build dependency graph
              |
         [2. flatten]      token-optimized single file with structural metadata
              |
     +--------+--------+
     |        |        |
  Claude   GPT-5.4  Gemini     [3. fire] - parallel via OpenRouter
     |        |        |
     +--------+--------+
              |
         [4. report]       cross-model synthesis, agreement/disagreement matrix
              |
     consultation report
```

Each model writes an independent consultation. The synthesis step identifies consensus findings, unique insights, and contradictions.

## Commands

| Command | Description |
|---------|-------------|
| `firehose auth` | Store your OpenRouter API key |
| `firehose scan <root>` | Scan codebase, generate `.firehose/manifest.yaml` |
| `firehose flatten` | Read manifest, produce flat text file |
| `firehose fire --models <list>` | Send payload to models via OpenRouter |
| `firehose report` | Synthesize cross-model comparison |
| `firehose analyze <root>` | Full pipeline (scan + flatten + fire + report) |
| `firehose models` | List available OpenRouter models with pricing |
| `firehose instruct` | Print agent-ready instructions to stdout |
| `firehose init` | Initialize `.firehose/` config directory |

## Default models

| Model | Context | Max Output | Provider |
|-------|---------|------------|----------|
| Claude Opus 4.6 | 1M tokens | 128K tokens | Anthropic |
| GPT-5.4 | 1.05M tokens | 128K tokens | OpenAI |
| Gemini 3.1 Pro | 1M tokens | 65K tokens | Google |

All three support extended reasoning. Firehose sends `reasoning.effort: "high"` by default, giving each model room to think before responding. Override with `--reasoning-effort`.

## Output structure

```
.firehose/
  manifest.yaml                # Scan output + flattening config (editable)
  runs/
    2026-03-10_143200/
      flat.txt                 # Flattened codebase
      prompt.md                # Analysis prompt sent to models
      payload.txt              # Prompt + flat file combined
      meta.json                # Run metadata (models, tokens, cost, latency)
      consultations/           # Per-model reports (markdown)
        anthropic--claude-opus-4.6.md
        openai--gpt-5.4.md
        google--gemini-3.1-pro-preview.md
      raw/                     # Full API response JSON
      comparison.md            # Cross-model synthesis
```

## The manifest

After scanning, `.firehose/manifest.yaml` controls flattening. Edit it to:

- **Reorder the sequence tree** - put entrypoints and core logic first; models attend more carefully to what they see early
- **Exclude files** - drop generated code, test fixtures, vendored deps
- **Regroup by domain** - organize by concern (auth, billing, rendering), not directory structure
- **Toggle stripping** - comments are stripped by default; keep them if they contain design rationale

## Agent integration

Firehose is built for coding agents. The `instruct` command emits a structured instruction block:

```bash
firehose instruct              # Full agent instructions
firehose instruct --compact    # Short version
firehose instruct --with-manifest  # Include current manifest summary

# Pipe directly to an agent
firehose instruct | claude --print
```

## Configuration

Firehose uses layered config with this precedence:

1. **CLI flags** (highest)
2. **Project config** - `.firehose/config.yaml` in the repo
3. **User config** - `~/.config/firehose/config.yaml`
4. **Defaults** (lowest)

API key resolution: environment variable > `~/.config/firehose/credentials` > error with setup instructions.

## Key flags

```
--models <list>        Comma-separated model IDs (required for fire/analyze)
--exclude <glob>       Exclude patterns at scan time (repeatable)
--prompt <path>        Custom analysis prompt (replaces default)
--max-tokens <n>       Output budget per model (default: 128000)
--reasoning-effort     high, xhigh, medium, low, or none (default: high)
--response-format      markdown or json (default: markdown)
--timeout <seconds>    Per-model timeout (default: 600)
--synthesis-model      Model for cross-model comparison (default: claude-opus-4.6)
```

## Development

```bash
git clone https://github.com/matthew-kissinger/firehose-cli.git
cd firehose-cli
uv sync
uv run firehose --help
uv run pytest
```

## License

MIT
