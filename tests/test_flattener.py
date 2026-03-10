"""Tests for the flattener module."""

import tempfile
from pathlib import Path

from firehose.core.flattener import (
    collapse_whitespace,
    flatten,
    resolve_sequence,
    strip_comments,
)
from firehose.models.manifest import (
    Manifest,
    ManifestMeta,
    LanguageStats,
    SequenceNode,
)


def test_strip_comments_python():
    code = "x = 1  # comment\ny = 2\n"
    result = strip_comments(code, "python")
    assert "# comment" not in result
    assert "x = 1" in result
    assert "y = 2" in result


def test_strip_comments_javascript():
    code = "const x = 1; // comment\n/* block */\nconst y = 2;\n"
    result = strip_comments(code, "javascript")
    assert "// comment" not in result
    assert "/* block */" not in result
    assert "const x = 1;" in result


def test_strip_comments_none_lang():
    code = "# not stripped\n"
    result = strip_comments(code, None)
    assert result == code


def test_collapse_whitespace_aggressive():
    text = "line1\n\n\n\n\nline2\n"
    result = collapse_whitespace(text, "aggressive")
    # Aggressive: no consecutive blank lines at all
    assert "\n\n" not in result
    assert "line1\nline2" == result


def test_collapse_whitespace_moderate():
    text = "line1\n\n\n\n\nline2\n"
    result = collapse_whitespace(text, "moderate")
    # Should collapse 5 newlines to 3
    assert "\n\n\n\n" not in result


def test_collapse_whitespace_none():
    text = "line1\n\n\n\n\nline2\n"
    result = collapse_whitespace(text, "none")
    assert result == text


def test_resolve_sequence():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "a.py").write_text("a", encoding="utf-8")
        (root / "b.py").write_text("b", encoding="utf-8")

        nodes = [
            SequenceNode(path="a.py"),
            SequenceNode(path="b.py"),
        ]
        files = resolve_sequence(nodes, root)
        assert len(files) == 2
        assert files[0].name == "a.py"
        assert files[1].name == "b.py"


def test_resolve_sequence_group():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "b.py").write_text("b", encoding="utf-8")
        (root / "a.py").write_text("a", encoding="utf-8")

        nodes = [
            SequenceNode(
                name="all",
                order="alphabetical",
                children=[
                    SequenceNode(path="b.py"),
                    SequenceNode(path="a.py"),
                ],
            ),
        ]
        files = resolve_sequence(nodes, root)
        # Alphabetical sort
        assert files[0].name == "a.py"
        assert files[1].name == "b.py"


def test_flatten_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "main.py").write_text("print('hello')\n", encoding="utf-8")

        manifest = Manifest(
            root=str(root),
            meta=ManifestMeta(
                total_files=1,
                total_tokens_est=5,
                total_chars=16,
                languages={"python": LanguageStats(files=1, tokens=5)},
            ),
            sequence=[SequenceNode(path="main.py")],
        )

        result = flatten(manifest)
        assert "FIREHOSE CODEBASE SNAPSHOT" in result
        assert "BEGIN SOURCE" in result
        assert "print('hello')" in result
        assert "main.py" in result
