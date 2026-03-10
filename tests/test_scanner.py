"""Tests for the scanner module."""

import tempfile
from pathlib import Path

from firehose.core.scanner import (
    detect_language,
    is_binary,
    is_entrypoint,
    scan_codebase,
    should_exclude,
)


def test_detect_language():
    assert detect_language(Path("main.py")) == "python"
    assert detect_language(Path("app.ts")) == "typescript"
    assert detect_language(Path("index.js")) == "javascript"
    assert detect_language(Path("lib.rs")) == "rust"
    assert detect_language(Path("main.go")) == "go"
    assert detect_language(Path("unknown.xyz")) is None


def test_is_binary():
    assert is_binary(Path("image.png"))
    assert is_binary(Path("font.woff2"))
    assert not is_binary(Path("code.py"))
    assert not is_binary(Path("config.yaml"))


def test_should_exclude():
    patterns = ["**/*.test.*", "**/node_modules/**", "**/.git/**"]
    assert should_exclude("src/app.test.ts", patterns)
    assert should_exclude("node_modules/pkg/index.js", patterns)
    assert not should_exclude("src/app.ts", patterns)


def test_is_entrypoint():
    assert is_entrypoint("src/main.py", "python")
    assert is_entrypoint("src/index.ts", "typescript")
    assert not is_entrypoint("src/utils.py", "python")
    assert not is_entrypoint("src/helpers.ts", "typescript")


def test_scan_codebase():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Create test files
        (root / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (root / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
        src = root / "src"
        src.mkdir()
        (src / "app.ts").write_text("export const app = 'hello';\n", encoding="utf-8")

        manifest = scan_codebase(root)

        assert manifest.meta.total_files == 3
        assert manifest.meta.total_tokens_est > 0
        assert manifest.meta.total_chars > 0
        assert "python" in manifest.meta.languages
        assert "typescript" in manifest.meta.languages
        assert len(manifest.sequence) > 0


def test_scan_excludes_binaries():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "code.py").write_text("x = 1\n", encoding="utf-8")
        (root / "image.png").write_bytes(b"\x89PNG")

        manifest = scan_codebase(root)
        assert manifest.meta.total_files == 1


def test_scan_excludes_patterns():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "app.py").write_text("x = 1\n", encoding="utf-8")
        (root / "app.test.py").write_text("test\n", encoding="utf-8")

        manifest = scan_codebase(root)
        assert manifest.meta.total_files == 1
