"""Codebase discovery, language detection, and manifest generation."""

from __future__ import annotations

import fnmatch
import re
from datetime import datetime, timezone
from pathlib import Path

from firehose.core.tokenizer import estimate_tokens_fast as estimate_tokens
from firehose.models.manifest import (
    DocsConfig,
    LanguageStats,
    Manifest,
    ManifestMeta,
    SequenceNode,
)

# Extension to language mapping
EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "csharp",
    ".scala": "scala",
    ".sc": "scala",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".vue": "vue",
    ".svelte": "svelte",
}

# Binary/non-code extensions to always skip
BINARY_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".pyc", ".pyo", ".class", ".wasm",
    ".sqlite", ".db",
}

# Well-known doc files
DOC_PATTERNS: list[str] = [
    "README.md", "README.rst", "README.txt", "README",
    "docs/**/*.md", "doc/**/*.md",
    "ARCHITECTURE.md", "DESIGN.md",
]

# Entrypoint detection patterns
ENTRYPOINT_PATTERNS: dict[str, list[str]] = {
    "python": ["main.py", "app.py", "__main__.py", "cli.py", "manage.py", "wsgi.py", "asgi.py"],
    "typescript": ["main.ts", "index.ts", "app.ts", "server.ts"],
    "javascript": ["main.js", "index.js", "app.js", "server.js"],
    "rust": ["main.rs", "lib.rs"],
    "go": ["main.go", "cmd/**/*.go"],
}

DEFAULT_EXCLUDES: list[str] = [
    "**/*.test.*", "**/*.spec.*", "**/fixtures/**",
    "**/node_modules/**", "**/.git/**", "**/dist/**", "**/build/**",
    "**/*.lock", "**/*.map", "**/__pycache__/**", "**/.venv/**",
    "**/.firehose/**", "**/target/**", "**/.tox/**", "**/.mypy_cache/**",
    "**/.pytest_cache/**", "**/.ruff_cache/**", "**/coverage/**",
    "**/.env", "**/.env.*",
]


def detect_language(path: Path) -> str | None:
    return EXTENSION_MAP.get(path.suffix.lower())


def is_binary(path: Path) -> bool:
    return path.suffix.lower() in BINARY_EXTENSIONS


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a glob pattern with ** support to a regex."""
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == '*':
            if i + 1 < len(pattern) and pattern[i + 1] == '*':
                # ** matches any number of path segments
                if i + 2 < len(pattern) and pattern[i + 2] == '/':
                    parts.append("(?:.*/)?")
                    i += 3
                else:
                    parts.append(".*")
                    i += 2
            else:
                parts.append("[^/]*")
                i += 1
        elif c == '?':
            parts.append("[^/]")
            i += 1
        elif c == '.':
            parts.append(r"\.")
            i += 1
        elif c == '/':
            parts.append("/")
            i += 1
        else:
            parts.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def should_exclude(rel_path: str, patterns: list[str]) -> bool:
    rel_path = rel_path.replace("\\", "/")
    for pattern in patterns:
        regex = _glob_to_regex(pattern)
        if regex.match(rel_path):
            return True
    return False


def is_entrypoint(rel_path: str, lang: str | None) -> bool:
    if lang is None:
        return False
    name = Path(rel_path).name
    patterns = ENTRYPOINT_PATTERNS.get(lang, [])
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


def detect_doc_files(root: Path) -> list[str]:
    docs: list[str] = []
    for pattern in DOC_PATTERNS:
        if "*" in pattern:
            for match in root.glob(pattern):
                if match.is_file():
                    docs.append(str(match.relative_to(root)))
        else:
            candidate = root / pattern
            if candidate.is_file():
                docs.append(pattern)
    return docs


def scan_codebase(
    root: Path,
    extra_include: list[str] | None = None,
    extra_exclude: list[str] | None = None,
) -> Manifest:
    """Walk the file tree and produce a Manifest."""
    import os

    root = root.resolve()
    exclude_patterns = DEFAULT_EXCLUDES + (extra_exclude or [])

    # Directories to always prune during walk (never descend into)
    PRUNE_DIRS = {
        "node_modules", ".git", "dist", "build", "__pycache__",
        ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", "target", "coverage", ".firehose",
        ".next", ".nuxt", "artifacts", "tmp",
    }

    # Also prune any directory matching exclude patterns
    exclude_dir_names: set[str] = set()
    for pat in exclude_patterns:
        # Extract bare directory names from patterns like **/dirname/**
        if pat.startswith("**/") and pat.endswith("/**"):
            dirname = pat[3:-3]
            if "/" not in dirname and "*" not in dirname:
                exclude_dir_names.add(dirname)
    PRUNE_DIRS |= exclude_dir_names

    files_by_lang: dict[str, list[tuple[str, int, int]]] = {}
    all_files: list[tuple[str, str | None, int, int]] = []
    entrypoints: list[str] = []
    total_tokens = 0
    total_chars = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune known-heavy directories in-place to skip them entirely
        rel_dir = str(Path(dirpath).relative_to(root)).replace("\\", "/")
        dirnames[:] = [
            d for d in dirnames
            if d not in PRUNE_DIRS
            and not should_exclude(f"{rel_dir}/{d}/x".lstrip("./"), exclude_patterns)
        ]
        dirnames.sort()

        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if is_binary(path):
                continue

            rel = str(path.relative_to(root)).replace("\\", "/")
            if should_exclude(rel, exclude_patterns):
                continue

            lang = detect_language(path)

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, PermissionError):
                continue

            chars = len(content)
            tokens = estimate_tokens(content)
            total_tokens += tokens
            total_chars += chars

            all_files.append((rel, lang, tokens, chars))

            if lang:
                files_by_lang.setdefault(lang, []).append((rel, tokens, chars))

            if is_entrypoint(rel, lang):
                entrypoints.append(rel)

    # Build language stats
    lang_stats: dict[str, LanguageStats] = {}
    for lang, file_list in sorted(files_by_lang.items(), key=lambda x: -sum(t for _, t, _ in x[1])):
        lang_stats[lang] = LanguageStats(
            files=len(file_list),
            tokens=sum(t for _, t, _ in file_list),
        )

    # Build sequence tree - group by top-level directory
    groups: dict[str, list[str]] = {}
    for rel, lang, tokens, chars in all_files:
        parts = rel.split("/")
        group_name = parts[0] if len(parts) > 1 else "root"
        groups.setdefault(group_name, []).append(rel)

    sequence: list[SequenceNode] = []

    # Entrypoints first if any
    if entrypoints:
        sequence.append(SequenceNode(
            name="entrypoints",
            order="manual",
            children=[SequenceNode(path=ep) for ep in entrypoints],
        ))

    # Then by directory group
    for group_name, file_paths in sorted(groups.items()):
        # Skip files already in entrypoints
        remaining = [fp for fp in file_paths if fp not in entrypoints]
        if not remaining:
            continue
        sequence.append(SequenceNode(
            name=group_name,
            order="alphabetical",
            children=[SequenceNode(path=fp) for fp in sorted(remaining)],
        ))

    # Detect docs
    doc_files = detect_doc_files(root)

    return Manifest(
        version=1,
        generated=datetime.now(timezone.utc).isoformat(),
        root=str(root),
        meta=ManifestMeta(
            total_files=len(all_files),
            total_tokens_est=total_tokens,
            total_chars=total_chars,
            languages=lang_stats,
            entrypoints_detected=entrypoints,
        ),
        exclude=exclude_patterns,
        docs=DocsConfig(files=doc_files),
        sequence=sequence,
    )


def save_manifest(manifest: Manifest, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(
            manifest.model_dump(mode="json"),
            f,
            default_flow_style=False,
            sort_keys=False,
        )
    return output_path


def load_manifest(path: Path) -> Manifest:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Manifest.model_validate(data)


# Import yaml here to avoid circular issues
import yaml
