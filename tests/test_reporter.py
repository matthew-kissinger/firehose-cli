"""Tests for the reporter module."""

import tempfile
from pathlib import Path

from firehose.core.reporter import (
    build_comparison_prompt,
    create_snapshot_dir,
    load_reports,
    sanitize_model_name,
    save_comparison,
    save_flat_file,
    save_response,
)
from firehose.models.response import ModelResponse


def test_sanitize_model_name():
    assert sanitize_model_name("anthropic/claude-opus-4-6") == "anthropic--claude-opus-4-6"
    assert sanitize_model_name("openai/gpt-5.4") == "openai--gpt-5.4"


def test_create_snapshot_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        fh_dir = Path(tmpdir) / ".firehose"
        fh_dir.mkdir()
        snap_dir = create_snapshot_dir(fh_dir)
        assert snap_dir.exists()
        assert (snap_dir / "raw").exists()
        assert (snap_dir / "consultations").exists()


def test_save_flat_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        snap_dir = Path(tmpdir)
        path = save_flat_file(snap_dir, "flat content here")
        assert path.exists()
        assert path.read_text() == "flat content here"


def test_save_and_load_response():
    with tempfile.TemporaryDirectory() as tmpdir:
        snap_dir = Path(tmpdir)
        (snap_dir / "raw").mkdir()
        (snap_dir / "consultations").mkdir()

        resp = ModelResponse(
            model="anthropic/claude-opus-4-6",
            provider="anthropic",
            status="complete",
            latency_ms=5000,
            tokens_prompt=1000,
            tokens_completion=2000,
            cost_usd=0.05,
            finish_reason="stop",
            generation_id="gen-123",
            raw_response="Great codebase analysis here.",
        )
        json_path, md_path = save_response(snap_dir, resp)
        assert json_path.exists()
        assert md_path.exists()
        assert md_path.read_text() == "Great codebase analysis here."

        reports = load_reports(snap_dir)
        assert "anthropic/claude-opus-4-6" in reports


def test_build_comparison_prompt():
    reports = {
        "model-a": "Report A content",
        "model-b": "Report B content",
    }
    prompt = build_comparison_prompt(reports)
    assert "model-a" in prompt
    assert "model-b" in prompt
    assert "Report A content" in prompt
    assert "Report B content" in prompt
    assert "High-Confidence Findings" in prompt
    assert "Unique Findings" in prompt
    assert "Prioritized Action Items" in prompt


def test_save_comparison():
    with tempfile.TemporaryDirectory() as tmpdir:
        snap_dir = Path(tmpdir)
        path = save_comparison(snap_dir, "# Comparison\nModels agree on X.")
        assert path.exists()
        assert "Comparison" in path.read_text()
