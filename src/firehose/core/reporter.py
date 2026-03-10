"""Response capture, report writing, and cross-model comparison."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from firehose.models.report import RunMeta
from firehose.models.response import ModelResponse


def sanitize_model_name(model: str) -> str:
    """Convert model ID to safe filename: anthropic/claude-opus-4.6 -> anthropic--claude-opus-4.6"""
    return model.replace("/", "--")


def create_snapshot_dir(firehose_dir: Path) -> Path:
    """Create a timestamped run directory."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    snap_dir = firehose_dir / "runs" / ts
    (snap_dir / "raw").mkdir(parents=True, exist_ok=True)
    (snap_dir / "consultations").mkdir(parents=True, exist_ok=True)
    return snap_dir


def get_latest_snapshot(firehose_dir: Path) -> Path | None:
    """Get the most recent run directory."""
    runs_dir = firehose_dir / "runs"
    if not runs_dir.exists():
        return None
    dirs = sorted(
        [d for d in runs_dir.iterdir() if d.is_dir()],
        reverse=True,
    )
    return dirs[0] if dirs else None


def save_flat_file(snap_dir: Path, content: str) -> Path:
    path = snap_dir / "flat.txt"
    path.write_text(content, encoding="utf-8")
    return path


def save_prompt(snap_dir: Path, prompt: str) -> Path:
    path = snap_dir / "prompt.md"
    path.write_text(prompt, encoding="utf-8")
    return path


def save_payload(snap_dir: Path, payload: str) -> Path:
    path = snap_dir / "payload.txt"
    path.write_text(payload, encoding="utf-8")
    return path


def save_response(snap_dir: Path, response: ModelResponse) -> tuple[Path, Path]:
    """Save raw JSON response and markdown consultation."""
    safe_name = sanitize_model_name(response.model)

    # Raw JSON
    json_path = snap_dir / "raw" / f"{safe_name}.json"
    json_path.write_text(
        json.dumps(response.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )

    # Markdown consultation (the raw_response IS the consultation in markdown mode)
    md_path = snap_dir / "consultations" / f"{safe_name}.md"
    md_path.write_text(response.raw_response, encoding="utf-8")

    return json_path, md_path


def save_run_meta(snap_dir: Path, meta: RunMeta) -> Path:
    path = snap_dir / "meta.json"
    path.write_text(
        json.dumps(meta.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return path


def load_reports(snap_dir: Path) -> dict[str, str]:
    """Load all markdown consultations from a run."""
    reports: dict[str, str] = {}
    consult_dir = snap_dir / "consultations"
    if consult_dir.exists():
        for md_file in sorted(consult_dir.glob("*.md")):
            model_name = md_file.stem.replace("--", "/")
            reports[model_name] = md_file.read_text(encoding="utf-8")
    return reports


def build_comparison_prompt(reports: dict[str, str]) -> str:
    """Build a prompt asking a model to synthesize multiple consultation reports."""
    model_names = list(reports.keys())
    model_count = len(model_names)

    parts = [
        f"You are synthesizing {model_count} independent code review consultations.",
        f"Each was produced by a different frontier model ({', '.join(model_names)})",
        "reviewing the exact same codebase. No model saw any other model's report.",
        "",
        "Your job is to find where they agree, where they disagree, and what each",
        "uniquely caught. Be concrete - reference specific file paths, function names,",
        "and code patterns from the reports. Do not summarize at a high level when the",
        "reports contain specific evidence.",
        "",
        "The reports vary in length and depth. A shorter report is not worse - it may",
        "just focus on fewer things more precisely. Judge by specificity and correctness,",
        "not volume.",
        "",
        "## Structure your synthesis as follows:",
        "",
        "### High-Confidence Findings (convergence)",
        "Concerns raised independently by 2+ models. For each, cite which models raised",
        "it and the specific files/code they referenced. These are the findings most",
        "likely to be real and important.",
        "",
        "### Disputed or Divergent Areas",
        "Where models disagree on severity, root cause, or recommended fix. Or where",
        "they focus on the same area but reach different conclusions. Flag these for",
        "human review with enough context to evaluate.",
        "",
        "### Unique Findings",
        "Specific bugs, architectural issues, or insights that only one model caught.",
        "These are higher-risk (single source) but may be the most valuable if correct.",
        "Note which model found each one.",
        "",
        "### Prioritized Action Items",
        "Based on the full synthesis, list the top 5-10 concrete actions in priority",
        "order. For each, note the confidence level (high = convergence, medium = single",
        "model but specific, low = subjective/stylistic).",
        "",
        "Do not editorialize on the models themselves. Do not rank them. Focus entirely",
        "on the codebase findings.",
        "",
        "---",
        "",
    ]

    for model, report in reports.items():
        parts.append(f"=== CONSULTATION FROM: {model} ===")
        parts.append("")
        parts.append(report)
        parts.append("")
        parts.append(f"=== END {model} ===")
        parts.append("")

    return "\n".join(parts)


def save_comparison(snap_dir: Path, comparison: str) -> Path:
    path = snap_dir / "comparison.md"
    path.write_text(comparison, encoding="utf-8")
    return path
