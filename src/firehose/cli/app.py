"""Typer CLI app with all subcommands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from firehose.config.settings import (
    FirehoseConfig,
    get_credentials_path,
    get_firehose_dir,
    load_config,
    load_credentials,
    save_config,
    save_credentials,
    MANIFEST_FILE,
)
from firehose.core.flattener import flatten
from firehose.core.prompter import build_payload, load_prompt
from firehose.core.reporter import (
    build_comparison_prompt,
    create_snapshot_dir,
    get_latest_snapshot,
    load_reports,
    save_comparison,
    save_flat_file,
    save_payload,
    save_prompt,
    save_response,
    save_run_meta,
)
from firehose.core.router import create_client, fire_all, fire_model, get_generation_stats
from firehose.core.scanner import load_manifest, save_manifest, scan_codebase
from firehose.models.report import RunMeta

app = typer.Typer(
    name="firehose",
    help="Flatten a codebase, fan out to LLMs, compare reports.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def auth(
    key: Optional[str] = typer.Option(None, "--key", "-k", help="API key (non-interactive)"),
    show: bool = typer.Option(False, "--show", help="Display stored key info"),
    remove: bool = typer.Option(False, "--remove", help="Remove stored credentials"),
):
    """Store your OpenRouter API key for global use."""
    creds_path = get_credentials_path()

    if remove:
        if creds_path.exists():
            creds_path.unlink()
            console.print(f"Removed credentials file: {creds_path}")
        else:
            console.print("No credentials file found.")
        return

    if show:
        creds = load_credentials()
        api_key = creds.get("OPENROUTER_API_KEY", "")
        if api_key:
            masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            console.print(f"  Key: {masked}")
            console.print(f"  File: {creds_path}")
        else:
            console.print("No API key stored. Run 'firehose auth' to set one.")
        return

    if not key:
        key = typer.prompt("OpenRouter API key", hide_input=True)

    if not key or not key.strip():
        console.print("[red]No key provided.[/red]")
        raise typer.Exit(1)

    key = key.strip()
    creds = load_credentials()
    creds["OPENROUTER_API_KEY"] = key
    save_credentials(creds)

    masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    console.print(f"[green]API key saved.[/green]")
    console.print(f"  Key: {masked}")
    console.print(f"  File: {creds_path}")


@app.command()
def init(
    root: Path = typer.Option(Path("."), "--root", "-r", help="Codebase root"),
):
    """Initialize a .firehose/ directory with default config."""
    fh_dir = get_firehose_dir(root)
    if (fh_dir / "config.yaml").exists():
        console.print(f"[yellow]Config already exists at {fh_dir / 'config.yaml'}[/yellow]")
        raise typer.Abort()

    fh_dir.mkdir(parents=True, exist_ok=True)

    # Write a human-readable commented config
    config_path = fh_dir / "config.yaml"
    config_path.write_text(
        "# Firehose CLI configuration\n"
        "# Docs: https://github.com/matthew-kissinger/firehose-cli\n"
        "\n"
        "openrouter:\n"
        "  # Environment variable containing your OpenRouter API key\n"
        "  # Get one at https://openrouter.ai/settings/keys\n"
        "  api_key_env: OPENROUTER_API_KEY\n"
        "\n"
        "defaults:\n"
        "  # Models to use for analysis (override with --models flag)\n"
        "  models:\n"
        "    - anthropic/claude-opus-4.6\n"
        "    - openai/gpt-5.4\n"
        "    - google/gemini-3.1-pro-preview\n"
        "\n"
        "  # Model used for cross-model comparison synthesis\n"
        "  synthesis_model: anthropic/claude-opus-4.6\n"
        "\n"
        "  # Max models running at once\n"
        "  max_concurrent: 5\n"
        "\n"
        "  # Per-model timeout in seconds (these are big jobs)\n"
        "  timeout_seconds: 600\n"
        "\n"
        "  # Output token budget per model (includes reasoning token overhead)\n"
        "  max_tokens: 128000\n"
        "\n"
        "  # Reasoning effort: high or xhigh (passed to models that support it)\n"
        "  reasoning_effort: high\n"
        "\n"
        "  # Response format: markdown (recommended) or json\n"
        "  response_format: markdown\n"
        "\n"
        "scan:\n"
        "  # Patterns excluded from every scan (extend with --exclude flag)\n"
        "  default_exclude:\n"
        "    - '**/*.test.*'\n"
        "    - '**/*.spec.*'\n"
        "    - '**/node_modules/**'\n"
        "    - '**/.git/**'\n"
        "    - '**/dist/**'\n"
        "    - '**/build/**'\n"
        "    - '**/*.lock'\n"
        "    - '**/*.map'\n"
        "    - '**/__pycache__/**'\n"
        "    - '**/.venv/**'\n",
        encoding="utf-8",
    )

    # Create .gitignore inside .firehose
    gitignore = fh_dir / ".gitignore"
    gitignore.write_text(
        "# Keep manifest (it's the curated flattening plan)\n"
        "# Ignore config (may reference API keys) and run artifacts\n"
        "config.yaml\n"
        "runs/\n",
        encoding="utf-8",
    )

    console.print(f"[green]Initialized .firehose/ at {fh_dir}[/green]")
    console.print(f"  Config: {config_path}")
    console.print(f"  .gitignore: {gitignore}")
    console.print(f"\n  Next: set OPENROUTER_API_KEY and run 'firehose scan <root>'")


@app.command()
def scan(
    root: Path = typer.Argument(Path("."), help="Codebase root to scan"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Manifest output path"),
    include: Optional[list[str]] = typer.Option(None, "--include", help="Additional include patterns"),
    exclude: Optional[list[str]] = typer.Option(None, "--exclude", help="Additional exclude patterns"),
):
    """Scan a codebase and generate .firehose/manifest.yaml."""
    root = root.resolve()
    if not root.is_dir():
        console.print(f"[red]Not a directory: {root}[/red]")
        raise typer.Exit(1)

    console.print("Scanning codebase...")
    manifest = scan_codebase(root, extra_include=include, extra_exclude=exclude)

    output_path = output or (get_firehose_dir(root) / MANIFEST_FILE)
    save_manifest(manifest, output_path)

    # Summary
    console.print(f"\n[green]Scan complete.[/green]")
    console.print(f"  Files: {manifest.meta.total_files}")
    console.print(f"  Tokens: ~{manifest.meta.total_tokens_est:,}")
    console.print(f"  Characters: {manifest.meta.total_chars:,}")
    if manifest.meta.languages:
        langs = ", ".join(
            f"{lang} ({stats.files} files)"
            for lang, stats in manifest.meta.languages.items()
        )
        console.print(f"  Languages: {langs}")
    if manifest.meta.entrypoints_detected:
        console.print(f"  Entrypoints: {', '.join(manifest.meta.entrypoints_detected)}")
    console.print(f"\n  Manifest: {output_path}")


@app.command(name="flatten")
def flatten_cmd(
    manifest_path: Optional[Path] = typer.Option(None, "--manifest", "-m", help="Manifest path"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output path"),
    strip_comments: Optional[bool] = typer.Option(None, "--strip-comments/--no-strip-comments"),
    include_docs: Optional[bool] = typer.Option(None, "--include-docs/--no-include-docs"),
    root: Path = typer.Option(Path("."), "--root", "-r", help="Codebase root"),
):
    """Read the manifest and produce a flat text file."""
    mpath = manifest_path or (get_firehose_dir(root) / MANIFEST_FILE)
    if not mpath.exists():
        console.print(f"[red]Manifest not found: {mpath}[/red]")
        console.print("Run 'firehose scan' first.")
        raise typer.Exit(1)

    manifest = load_manifest(mpath)

    console.print("Flattening codebase...")
    flat_content = flatten(manifest, strip_comments, include_docs)

    # Save to snapshot
    fh_dir = get_firehose_dir(root)
    snap_dir = create_snapshot_dir(fh_dir)
    flat_path = save_flat_file(snap_dir, flat_content)

    console.print(f"\n[green]Flattened {manifest.meta.total_files} files.[/green]")
    console.print(f"  Output: {flat_path}")
    console.print(f"  Size: {len(flat_content):,} chars")


@app.command()
def fire(
    models: str = typer.Option(..., "--models", "-m", help="Comma-separated model IDs"),
    snapshot: Optional[Path] = typer.Option(None, "--snapshot", "-s", help="Snapshot directory"),
    prompt_path: Optional[Path] = typer.Option(None, "--prompt", "-p", help="Custom prompt file"),
    max_concurrent: int = typer.Option(5, "--max-concurrent", help="Concurrency limit"),
    timeout: int = typer.Option(600, "--timeout", help="Per-model timeout in seconds"),
    max_tokens: int = typer.Option(128000, "--max-tokens", help="Output token budget per model"),
    reasoning_effort: str = typer.Option("high", "--reasoning-effort", help="high or xhigh"),
    response_format: str = typer.Option("markdown", "--response-format", help="markdown or json"),
    root: Path = typer.Option(Path("."), "--root", "-r", help="Codebase root"),
):
    """Send the flat file to multiple models via OpenRouter."""
    fh_dir = get_firehose_dir(root)

    # Find snapshot
    if snapshot:
        snap_dir = snapshot
    else:
        snap_dir = get_latest_snapshot(fh_dir)
        if not snap_dir:
            console.print("[red]No snapshots found. Run 'firehose flatten' first.[/red]")
            raise typer.Exit(1)

    flat_path = snap_dir / "flat.txt"
    if not flat_path.exists():
        console.print(f"[red]No flat.txt in snapshot: {snap_dir}[/red]")
        raise typer.Exit(1)

    flat_content = flat_path.read_text(encoding="utf-8")
    prompt = load_prompt(prompt_path)
    payload = build_payload(prompt, flat_content)

    # Save prompt and payload
    save_prompt(snap_dir, prompt)
    save_payload(snap_dir, payload)

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    config = load_config(root)

    console.print(f"\n[bold]Firing to {len(model_list)} models...[/bold]")
    for m in model_list:
        console.print(f"  - {m}")
    console.print()

    # Run async dispatch
    responses = asyncio.run(
        fire_all(
            model_list, payload, config,
            max_concurrent=max_concurrent,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            timeout=timeout,
            response_format=response_format,
        )
    )

    # Save responses and build summary table
    table = Table(title="Results")
    table.add_column("Model", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Tokens", justify="right")
    table.add_column("Latency", justify="right")
    table.add_column("Cost", justify="right")

    completed = 0
    failed = 0
    total_cost = 0.0
    max_latency = 0

    for resp in responses:
        save_response(snap_dir, resp)

        status_style = {
            "complete": "[green]complete[/green]",
            "failed": "[red]failed[/red]",
            "timeout": "[yellow]timeout[/yellow]",
        }.get(resp.status, resp.status)

        table.add_row(
            resp.model,
            status_style,
            f"{resp.tokens_completion:,}" if resp.tokens_completion else "-",
            f"{resp.latency_ms / 1000:.1f}s",
            f"${resp.cost_usd:.4f}" if resp.cost_usd else "-",
        )

        if resp.status == "complete":
            completed += 1
        else:
            failed += 1
        total_cost += resp.cost_usd
        max_latency = max(max_latency, resp.latency_ms)

    console.print(table)

    # Save run metadata
    meta = RunMeta(
        timestamp=snap_dir.name,
        codebase_root=str(root),
        total_files=0,
        total_tokens_est=0,
        models_requested=model_list,
        models_completed=completed,
        models_failed=failed,
        total_cost_usd=total_cost,
        total_latency_max_ms=max_latency,
    )
    save_run_meta(snap_dir, meta)

    console.print(f"\n[green]Done.[/green] {completed} complete, {failed} failed.")
    console.print(f"  Snapshot: {snap_dir}")


@app.command()
def report(
    snapshot: Optional[Path] = typer.Option(None, "--snapshot", "-s", help="Snapshot to analyze"),
    synthesis_model: Optional[str] = typer.Option(None, "--synthesis-model", help="Model for comparison"),
    format: str = typer.Option("md", "--format", "-f", help="Output format: md or json"),
    root: Path = typer.Option(Path("."), "--root", "-r", help="Codebase root"),
):
    """Synthesize and compare model responses from a completed run."""
    fh_dir = get_firehose_dir(root)

    snap_dir = snapshot or get_latest_snapshot(fh_dir)
    if not snap_dir:
        console.print("[red]No snapshots found.[/red]")
        raise typer.Exit(1)

    reports = load_reports(snap_dir)
    if not reports:
        console.print(f"[red]No consultations found in {snap_dir / 'consultations'}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Synthesizing {len(reports)} reports...[/bold]")
    for model in reports:
        console.print(f"  - {model}")

    # Build comparison prompt and send to synthesis model
    comparison_prompt = build_comparison_prompt(reports)

    config = load_config(root)

    # Use configured synthesis model as default
    if not synthesis_model:
        synthesis_model = config.defaults.synthesis_model
    console.print(f"\n  Synthesis model: {synthesis_model}")

    responses = asyncio.run(
        fire_all(
            [synthesis_model],
            comparison_prompt,
            config,
            max_tokens=128000,
        )
    )

    if responses and responses[0].status == "complete":
        comparison = responses[0].raw_response
        save_comparison(snap_dir, comparison)
        console.print(f"\n[green]Comparison saved to {snap_dir / 'comparison.md'}[/green]")
    else:
        error = responses[0].error if responses else "No response"
        console.print(f"[red]Synthesis failed: {error}[/red]")
        raise typer.Exit(1)


@app.command()
def analyze(
    root: Path = typer.Argument(Path("."), help="Codebase root"),
    models: str = typer.Option(..., "--models", "-m", help="Comma-separated model IDs (required)"),
    prompt_path: Optional[Path] = typer.Option(None, "--prompt", "-p", help="Custom prompt file"),
    include_docs: Optional[bool] = typer.Option(None, "--include-docs/--no-include-docs"),
    strip_comments: Optional[bool] = typer.Option(None, "--strip-comments/--no-strip-comments"),
    max_concurrent: int = typer.Option(5, "--max-concurrent"),
    timeout: int = typer.Option(600, "--timeout"),
    max_tokens: int = typer.Option(128000, "--max-tokens"),
    reasoning_effort: str = typer.Option("high", "--reasoning-effort"),
    response_format: str = typer.Option("markdown", "--response-format"),
):
    """Full pipeline: scan -> flatten -> fire -> report."""
    console.print("[bold]Running full pipeline...[/bold]\n")

    # 1. Scan
    console.rule("Step 1: Scan")
    root = root.resolve()
    manifest = scan_codebase(root)
    manifest_path = get_firehose_dir(root) / MANIFEST_FILE
    save_manifest(manifest, manifest_path)
    console.print(f"  Scanned {manifest.meta.total_files} files ({manifest.meta.total_tokens_est:,} tokens)")

    # 2. Flatten
    console.rule("Step 2: Flatten")
    flat_content = flatten(manifest, strip_comments, include_docs)
    fh_dir = get_firehose_dir(root)
    snap_dir = create_snapshot_dir(fh_dir)
    save_flat_file(snap_dir, flat_content)
    console.print(f"  Flattened to {len(flat_content):,} chars")

    # 3. Fire
    console.rule("Step 3: Fire")
    prompt = load_prompt(prompt_path)
    payload = build_payload(prompt, flat_content)
    save_prompt(snap_dir, prompt)
    save_payload(snap_dir, payload)

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    config = load_config(root)

    console.print(f"  Sending to {len(model_list)} models...")
    responses = asyncio.run(
        fire_all(
            model_list, payload, config,
            max_concurrent=max_concurrent,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            timeout=timeout,
            response_format=response_format,
        )
    )

    completed = sum(1 for r in responses if r.status == "complete")
    failed = sum(1 for r in responses if r.status != "complete")
    for resp in responses:
        save_response(snap_dir, resp)
    console.print(f"  {completed} complete, {failed} failed")

    # Save meta
    meta = RunMeta(
        timestamp=snap_dir.name,
        codebase_root=str(root),
        total_files=manifest.meta.total_files,
        total_tokens_est=manifest.meta.total_tokens_est,
        models_requested=model_list,
        models_completed=completed,
        models_failed=failed,
    )
    save_run_meta(snap_dir, meta)

    # 4. Report
    if completed >= 2:
        console.rule("Step 4: Report")
        reports = load_reports(snap_dir)
        comparison_prompt = build_comparison_prompt(reports)
        synthesis_model = config.defaults.synthesis_model
        console.print(f"  Synthesizing with {synthesis_model}...")

        synth_responses = asyncio.run(
            fire_all([synthesis_model], comparison_prompt, config, max_tokens=128000)
        )
        if synth_responses and synth_responses[0].status == "complete":
            save_comparison(snap_dir, synth_responses[0].raw_response)
            console.print(f"  [green]Comparison saved.[/green]")
        else:
            console.print("  [yellow]Comparison synthesis failed.[/yellow]")
    elif completed == 1:
        console.print("\n[yellow]Only 1 model completed - skipping comparison.[/yellow]")
    else:
        console.print("\n[red]No models completed successfully.[/red]")

    console.print(f"\n[bold green]Pipeline complete.[/bold green]")
    console.print(f"  Snapshot: {snap_dir}")


@app.command()
def instruct(
    root: Path = typer.Option(Path("."), "--root", "-r", help="Codebase root"),
    with_manifest: bool = typer.Option(False, "--with-manifest", help="Include manifest summary"),
    compact: bool = typer.Option(False, "--compact", help="Shorter output"),
):
    """Print agent-ready instructions to stdout."""
    instructions = _build_instructions(root, with_manifest, compact)
    # Print raw to stdout for piping
    typer.echo(instructions)


def _build_instructions(root: Path, with_manifest: bool, compact: bool) -> str:
    parts = [
        "# Firehose CLI - Agent Instructions",
        "",
        "Firehose flattens a codebase into a single text file, sends it to multiple",
        "frontier LLMs via OpenRouter in parallel, and compares their analysis reports.",
        "",
        "## Commands (in order)",
        "",
        "1. `firehose scan <root>` - Scan codebase, generate .firehose/manifest.yaml",
        "2. `firehose flatten` - Read manifest, produce flat text file",
        "3. `firehose fire --models <list>` - Send to models via OpenRouter",
        "4. `firehose report` - Synthesize and compare model responses",
        "",
        "Or run the full pipeline:",
        "  `firehose analyze <root> --models model1,model2,model3`",
        "",
    ]

    if not compact:
        parts.extend([
            "## Before You Scan",
            "",
            "Think before you scan. Not everything belongs in the payload.",
            "",
            "- **Scope the root.** Point `scan` at `src/` or the relevant subtree, not the",
            "  entire repo. Reference code, example directories, vendored deps, and assets",
            "  are noise that wastes tokens and dilutes the analysis.",
            "- **Exclude at scan time.** Use `--exclude` flags to drop directories and patterns",
            "  before they ever hit the manifest:",
            "  `firehose scan ./src --exclude 'examples' --exclude 'vendor' --exclude '*.test.*'`",
            "- **Check the scan output.** Look at file count and token estimate. If it is over",
            "  500K tokens, you almost certainly included something you should not have.",
            "  Common offenders: test fixtures, generated code, data files, example dirs,",
            "  migration files, vendored third-party code.",
            "",
            "## Manifest Editing",
            "",
            "After scanning, read .firehose/manifest.yaml and curate it:",
            "",
            "- **Reorder the sequence tree.** Put the most important code first - entrypoints,",
            "  core domain logic, then supporting infrastructure. Models attend more carefully",
            "  to what they see first.",
            "- **Remove irrelevant files.** Delete sequence nodes for generated code, config",
            "  boilerplate, or anything that does not warrant expert review.",
            "- **Regroup into logical sections.** Name groups by domain concern (auth, billing,",
            "  rendering) not by directory structure. Help the model build a mental model.",
            "- **Add exclude patterns** for anything the scan picked up that should not be flattened",
            "  (e.g. `**/*.generated.*`, `**/migrations/**`).",
            "- **Toggle stripping.** Comment stripping saves tokens but loses context. Keep",
            "  comments if they contain important design rationale.",
            "",
            "## Key Flags",
            "",
            "- `--models` - Comma-separated model IDs (e.g. anthropic/claude-opus-4-6,openai/gpt-5.4)",
            "- `--exclude <glob>` - Exclude patterns at scan time (repeatable)",
            "- `--prompt <path>` - Custom analysis prompt (replaces default)",
            "- `--max-tokens <n>` - Output budget per model (default: 128000)",
            "- `--reasoning-effort <level>` - high or xhigh",
            "- `--include-docs/--no-include-docs` - Include/exclude documentation",
            "- `--strip-comments/--no-strip-comments` - Override comment stripping at flatten time",
            "",
            "## Token Budget Guide",
            "",
            "All target models support ~1M token context. Aim to keep the flattened payload",
            "under 300K tokens for best analysis quality. Bigger is not better - a focused",
            "payload of the code that matters produces sharper reports than a dump of everything.",
            "",
        ])

    if with_manifest:
        manifest_path = get_firehose_dir(root) / MANIFEST_FILE
        if manifest_path.exists():
            manifest = load_manifest(manifest_path)
            parts.extend([
                "## Current Manifest Summary",
                "",
                f"- Files: {manifest.meta.total_files}",
                f"- Tokens: ~{manifest.meta.total_tokens_est:,}",
                f"- Languages: {', '.join(manifest.meta.languages.keys())}",
                f"- Entrypoints: {', '.join(manifest.meta.entrypoints_detected) or 'none detected'}",
                "",
            ])

    return "\n".join(parts)


@app.command(name="models")
def models_cmd(
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter by name/provider"),
    sort: str = typer.Option("name", "--sort", "-s", help="Sort by: price, context, name"),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass cache"),
):
    """List available models from OpenRouter."""
    import httpx
    from firehose.config.settings import get_api_key, load_config

    config = load_config()
    api_key = get_api_key(config)

    console.print("Fetching models from OpenRouter...")
    resp = httpx.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    resp.raise_for_status()
    data = resp.json()
    models_list = data.get("data", [])

    # Filter
    if filter:
        filter_lower = filter.lower()
        models_list = [
            m for m in models_list
            if filter_lower in m.get("id", "").lower()
            or filter_lower in m.get("name", "").lower()
        ]

    # Sort
    if sort == "context":
        models_list.sort(key=lambda m: m.get("context_length", 0), reverse=True)
    elif sort == "price":
        models_list.sort(key=lambda m: float(m.get("pricing", {}).get("prompt", "0")))
    else:
        models_list.sort(key=lambda m: m.get("id", ""))

    table = Table(title=f"OpenRouter Models ({len(models_list)})")
    table.add_column("ID", style="cyan", max_width=45)
    table.add_column("Context", justify="right")
    table.add_column("Prompt $/M", justify="right")
    table.add_column("Completion $/M", justify="right")

    for m in models_list[:50]:  # Cap at 50 for readability
        ctx = m.get("context_length", 0)
        pricing = m.get("pricing", {})
        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
        comp_price = float(pricing.get("completion", "0")) * 1_000_000

        table.add_row(
            m.get("id", ""),
            f"{ctx:,}" if ctx else "-",
            f"${prompt_price:.2f}" if prompt_price else "free",
            f"${comp_price:.2f}" if comp_price else "free",
        )

    console.print(table)
    if len(models_list) > 50:
        console.print(f"[dim]...and {len(models_list) - 50} more. Use --filter to narrow results.[/dim]")
