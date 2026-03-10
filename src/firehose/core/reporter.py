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
    """Build a prompt asking a model to synthesize multiple reports."""
    parts = [
        "You are synthesizing analysis reports from multiple AI models that each",
        "independently reviewed the same codebase. Your job is to identify patterns",
        "of agreement and disagreement across these reports.",
        "",
        "For each report below, a different model reviewed the same code and wrote",
        "its analysis independently. No model saw any other model's report.",
        "",
        "Produce a comparison that:",
        "1. CONVERGENCE: Concerns or observations raised independently by multiple models (high-confidence findings)",
        "2. DIVERGENCE: Areas where models disagree or focus on different things (flagged for human attention)",
        "3. UNIQUE INSIGHTS: Notable observations that only one model caught",
        "",
        "Do not editorialize. Do not rank the models. Just surface the patterns.",
        "",
    ]

    for model, report in reports.items():
        parts.append(f"=== REPORT FROM: {model} ===")
        parts.append(report)
        parts.append("")

    return "\n".join(parts)


def save_comparison(snap_dir: Path, comparison: str) -> Path:
    path = snap_dir / "comparison.md"
    path.write_text(comparison, encoding="utf-8")
    return path
