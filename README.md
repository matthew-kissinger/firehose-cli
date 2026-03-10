# Firehose

Flatten a codebase into a single file, fan it out to multiple frontier LLMs via OpenRouter in parallel, and compare their analysis reports.

Designed for coding agents (Claude Code, Codex CLI, Gemini CLI) but works directly from the command line.

## How it works

1. **Scan** a codebase - discovers files, detects languages, builds a dependency-aware sequence
2. **Flatten** into a single token-optimized text file - strips comments, collapses whitespace, adds structural metadata
3. **Fire** the payload to multiple frontier models simultaneously via OpenRouter
4. **Report** - synthesize and compare what each model found

Each model independently reviews the full codebase and writes a consultation. Where multiple models independently raise the same concern, that's a high-confidence finding. Where they diverge, that's flagged for human attention.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/mkissinger/firehose-cli.git
cd firehose-cli
uv sync
```

Set your OpenRouter API key:

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
```

## Quick start

```bash
# Full pipeline - scan, flatten, fire, compare
firehose analyze ./src --models anthropic/claude-opus-4.6,openai/gpt-5.4,google/gemini-3.1-pro-preview

# Or step by step for more control
firehose scan ./src --exclude "**/examples/**" --exclude "**/vendor/**"
# Edit .firehose/manifest.yaml to curate sequence and exclusions
firehose flatten
firehose fire --models anthropic/claude-opus-4.6,openai/gpt-5.4
firehose report
```

## Commands

| Command | Description |
|---------|-------------|
| `firehose scan <root>` | Scan codebase, generate `.firehose/manifest.yaml` |
| `firehose flatten` | Read manifest, produce flat text file |
| `firehose fire --models <list>` | Send payload to models via OpenRouter |
| `firehose report` | Synthesize cross-model comparison |
| `firehose analyze <root>` | Full pipeline (scan + flatten + fire + report) |
| `firehose models` | List available OpenRouter models |
| `firehose instruct` | Print agent-ready instructions to stdout |
| `firehose init` | Initialize `.firehose/` config directory |

## Output structure

Firehose creates a `.firehose/` directory at the repo root:

```
.firehose/
  manifest.yaml              # Scan output + flattening config (editable)
  runs/
    2026-03-10_143200/
      flat.txt               # Flattened codebase
      prompt.md              # Analysis prompt used
      payload.txt            # Prompt + flat file (what was sent)
      meta.json              # Run metadata (models, tokens, cost, latency)
      consultations/         # Per-model analysis reports
        anthropic--claude-opus-4.6.md
        openai--gpt-5.4.md
        google--gemini-3.1-pro-preview.md
      raw/                   # Full API response JSON
        anthropic--claude-opus-4.6.json
        ...
      comparison.md          # Cross-model synthesis
```

## The manifest

After scanning, `.firehose/manifest.yaml` controls how flattening works. Edit it to:

- **Reorder the sequence tree** - put important code first, models attend more carefully to what they see first
- **Exclude files** - drop generated code, test fixtures, vendored deps
- **Regroup by domain** - organize by concern, not directory structure
- **Toggle stripping** - comments are stripped by default, keep them if they contain design rationale

## Agent integration

The `instruct` command emits a structured instruction block that tells an agent how to use Firehose:

```bash
firehose instruct              # Full instructions
firehose instruct --compact    # Short version
firehose instruct --with-manifest  # Include current manifest summary
```

Agents should scope their scans, exclude noise, review the manifest, and curate before firing. See `firehose instruct` for the full workflow.

## Default models

| Model | Context | Provider |
|-------|---------|----------|
| Claude Opus 4.6 | 1M tokens | Anthropic |
| GPT-5.4 | 1.05M tokens | OpenAI |
| Gemini 3.1 Pro | 1M tokens | Google |

All frontier models with 1M+ context. A typical codebase flattened with comment stripping lands around 150K-500K tokens.

## Key flags

```
--models <list>        Comma-separated model IDs (required for fire/analyze)
--exclude <glob>       Exclude patterns at scan time (repeatable)
--prompt <path>        Custom analysis prompt (replaces default)
--max-tokens <n>       Output budget per model (default: 16384)
--reasoning-effort     high or xhigh (default: high)
--response-format      markdown or json (default: markdown)
--timeout <seconds>    Per-model timeout (default: 600)
```

## License

MIT
