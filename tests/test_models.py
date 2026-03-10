"""Tests for Pydantic models."""

from firehose.models.manifest import (
    LanguageStats,
    Manifest,
    ManifestMeta,
    SequenceNode,
    StripConfig,
)
from firehose.models.response import AnalysisReport, ModelResponse
from firehose.models.report import RunMeta


def test_sequence_node_leaf():
    node = SequenceNode(path="src/main.ts")
    assert node.is_leaf()
    assert not node.is_group()


def test_sequence_node_group():
    node = SequenceNode(
        name="core",
        children=[SequenceNode(path="src/a.ts"), SequenceNode(path="src/b.ts")],
    )
    assert node.is_group()
    assert not node.is_leaf()


def test_sequence_node_recursive():
    tree = SequenceNode(
        name="root",
        children=[
            SequenceNode(path="a.ts"),
            SequenceNode(
                name="nested",
                children=[SequenceNode(path="b.ts")],
            ),
        ],
    )
    assert tree.is_group()
    assert tree.children[0].is_leaf()
    assert tree.children[1].is_group()
    assert tree.children[1].children[0].is_leaf()


def test_manifest_defaults():
    m = Manifest()
    assert m.version == 1
    assert m.strip.comments is True
    assert m.strip.whitespace == "aggressive"
    assert len(m.exclude) > 0
    assert m.output.file_tree is True


def test_manifest_meta():
    meta = ManifestMeta(
        total_files=10,
        total_tokens_est=5000,
        total_chars=20000,
        languages={"python": LanguageStats(files=8, tokens=4000)},
    )
    assert meta.languages["python"].files == 8


def test_manifest_roundtrip():
    m = Manifest(
        root="./src",
        meta=ManifestMeta(total_files=5, total_tokens_est=1000, total_chars=4000),
        sequence=[
            SequenceNode(name="entry", children=[SequenceNode(path="main.py")]),
        ],
    )
    data = m.model_dump(mode="json")
    restored = Manifest.model_validate(data)
    assert restored.root == "./src"
    assert restored.meta.total_files == 5
    assert len(restored.sequence) == 1
    assert restored.sequence[0].children[0].path == "main.py"


def test_strip_config():
    s = StripConfig()
    assert s.comments is True
    assert s.whitespace == "aggressive"
    assert s.imports is False


def test_model_response():
    r = ModelResponse(
        model="anthropic/claude-opus-4-6",
        provider="anthropic",
        status="complete",
        latency_ms=5000,
        tokens_prompt=1000,
        tokens_completion=2000,
        cost_usd=0.05,
        finish_reason="stop",
        generation_id="gen-123",
        raw_response="This is the analysis...",
    )
    assert r.status == "complete"
    assert r.report is None


def test_model_response_with_report():
    report = AnalysisReport(
        consultation="Good code.",
        files_referenced=["main.py"],
        key_concerns=["no tests"],
        key_strengths=["clean API"],
    )
    r = ModelResponse(
        model="openai/gpt-5.4",
        provider="openai",
        status="complete",
        latency_ms=3000,
        tokens_prompt=500,
        tokens_completion=1000,
        cost_usd=0.02,
        finish_reason="stop",
        generation_id="gen-456",
        raw_response="{}",
        report=report,
    )
    assert r.report is not None
    assert r.report.key_concerns == ["no tests"]


def test_run_meta():
    meta = RunMeta(
        timestamp="2026-03-09T143200",
        codebase_root="./src",
        total_files=47,
        total_tokens_est=38400,
        models_requested=["anthropic/claude-opus-4-6", "openai/gpt-5.4"],
        models_completed=2,
    )
    assert meta.models_completed == 2
    assert len(meta.models_requested) == 2
