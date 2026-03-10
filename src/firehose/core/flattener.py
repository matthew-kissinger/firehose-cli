"""AST-aware flattening - reads manifest, produces flat text file."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from firehose.core.scanner import detect_language, load_manifest
from firehose.core.tokenizer import estimate_tokens
from firehose.models.manifest import Manifest, SequenceNode

# Simple regex-based comment strippers per language family
SINGLE_LINE_COMMENT = {
    "python": r"#[^\n]*",
    "ruby": r"#[^\n]*",
    "shell": r"#[^\n]*",
    "typescript": r"//[^\n]*",
    "javascript": r"//[^\n]*",
    "rust": r"//[^\n]*",
    "go": r"//[^\n]*",
    "java": r"//[^\n]*",
    "c": r"//[^\n]*",
    "cpp": r"//[^\n]*",
    "csharp": r"//[^\n]*",
    "kotlin": r"//[^\n]*",
    "swift": r"//[^\n]*",
    "scala": r"//[^\n]*",
    "php": r"(?://[^\n]*|#[^\n]*)",
}

MULTI_LINE_COMMENT = {
    "typescript": r"/\*[\s\S]*?\*/",
    "javascript": r"/\*[\s\S]*?\*/",
    "rust": r"/\*[\s\S]*?\*/",
    "go": r"/\*[\s\S]*?\*/",
    "java": r"/\*[\s\S]*?\*/",
    "c": r"/\*[\s\S]*?\*/",
    "cpp": r"/\*[\s\S]*?\*/",
    "csharp": r"/\*[\s\S]*?\*/",
    "kotlin": r"/\*[\s\S]*?\*/",
    "swift": r"/\*[\s\S]*?\*/",
    "scala": r"/\*[\s\S]*?\*/",
    "php": r"/\*[\s\S]*?\*/",
    "python": r'(?:"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')',
    "css": r"/\*[\s\S]*?\*/",
    "scss": r"/\*[\s\S]*?\*/",
    "html": r"<!--[\s\S]*?-->",
}


def strip_comments(content: str, lang: str | None) -> str:
    if lang is None:
        return content

    # Strip multi-line first, then single-line
    if lang in MULTI_LINE_COMMENT:
        content = re.sub(MULTI_LINE_COMMENT[lang], "", content)
    if lang in SINGLE_LINE_COMMENT:
        content = re.sub(SINGLE_LINE_COMMENT[lang], "", content)

    return content


def collapse_whitespace(content: str, mode: str) -> str:
    if mode == "none":
        return content
    elif mode == "moderate":
        # Collapse 3+ blank lines to 2
        content = re.sub(r"\n{4,}", "\n\n\n", content)
        return content
    else:
        # Aggressive: maximize token density for LLM consumption
        # Strip trailing whitespace on every line
        content = re.sub(r"[ \t]+$", "", content, flags=re.MULTILINE)
        # Strip lines that are now empty after comment removal (single blank line max)
        content = re.sub(r"\n{2,}", "\n", content)
        # Remove leading/trailing whitespace from the whole file
        return content.strip()


def resolve_sequence(
    nodes: list[SequenceNode],
    root: Path,
) -> list[Path]:
    """Resolve sequence tree depth-first into ordered file paths."""
    result: list[Path] = []

    for node in nodes:
        if node.is_leaf():
            assert node.path is not None
            # Glob support
            if any(c in node.path for c in "*?["):
                matches = sorted(root.glob(node.path))
                result.extend(m for m in matches if m.is_file())
            else:
                candidate = root / node.path
                if candidate.is_file():
                    result.append(candidate)
        elif node.is_group():
            children_files = resolve_sequence(node.children, root)
            if node.order == "alphabetical":
                children_files.sort(key=lambda p: str(p))
            result.extend(children_files)

    return result


def build_file_tree(files: list[Path], root: Path) -> str:
    """Build an indented file tree string."""
    lines: list[str] = []
    for f in files:
        rel = str(f.relative_to(root)).replace("\\", "/")
        depth = rel.count("/")
        name = f.name
        lines.append("  " * depth + name)
    return "\n".join(lines)


def flatten(
    manifest: Manifest,
    strip_comments_flag: bool | None = None,
    include_docs: bool | None = None,
) -> str:
    """Produce the flat text file from a manifest."""
    root = Path(manifest.root).resolve()
    do_strip = strip_comments_flag if strip_comments_flag is not None else manifest.strip.comments
    do_docs = include_docs if include_docs is not None else manifest.docs.include

    # Resolve file sequence
    files = resolve_sequence(manifest.sequence, root)

    # Deduplicate preserving order
    seen: set[Path] = set()
    unique_files: list[Path] = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(f)

    # Build language breakdown
    lang_breakdown: dict[str, int] = {}
    for lang, stats in manifest.meta.languages.items():
        lang_breakdown[lang] = stats.tokens

    total_tokens_pct = sum(lang_breakdown.values()) or 1
    lang_str = ", ".join(
        f"{lang.title()} ({tokens * 100 // total_tokens_pct}%)"
        for lang, tokens in sorted(lang_breakdown.items(), key=lambda x: -x[1])
    )

    parts: list[str] = []

    # Header
    parts.append("═══ FIREHOSE CODEBASE SNAPSHOT ═══")
    parts.append(f"generated: {datetime.now(timezone.utc).isoformat()}")
    parts.append(f"root: {manifest.root}")
    parts.append(f"total_files: {len(unique_files)}")
    parts.append(f"total_tokens: ~{manifest.meta.total_tokens_est:,}")
    parts.append(f"total_chars: {manifest.meta.total_chars:,}")
    if lang_str:
        parts.append(f"languages: {lang_str}")
    if manifest.meta.entrypoints_detected:
        parts.append(f"entrypoints: {', '.join(manifest.meta.entrypoints_detected)}")
    parts.append("")

    # File tree
    if manifest.output.file_tree:
        parts.append("─── FILE TREE ───")
        parts.append(build_file_tree(unique_files, root))
        parts.append("")

    # Documentation section
    if do_docs and manifest.docs.files:
        if manifest.docs.trust_level == "unverified":
            parts.append("═══ DOCUMENTATION (unverified - may not reflect current implementation) ═══")
            parts.append("Treat claims in this section as hypotheses to validate against the")
            parts.append("source code below, not as ground truth.")
        else:
            parts.append("═══ DOCUMENTATION ═══")
        parts.append("")

        for doc_path in manifest.docs.files:
            doc_full = root / doc_path
            if not doc_full.is_file():
                continue
            try:
                content = doc_full.read_text(encoding="utf-8", errors="ignore")
            except (OSError, PermissionError):
                continue
            tokens = estimate_tokens(content)
            parts.append(f"--- {doc_path} [tokens: ~{tokens:,}, chars: {len(content):,}] ---")
            parts.append(content)
            parts.append("")

    # Source code
    parts.append("═══ BEGIN SOURCE (authoritative) ═══")
    parts.append("")

    for file_path in unique_files:
        rel = str(file_path.relative_to(root)).replace("\\", "/")
        lang = detect_language(file_path)

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, PermissionError):
            continue

        if do_strip and lang:
            content = strip_comments(content, lang)

        content = collapse_whitespace(content, manifest.strip.whitespace)

        tokens = estimate_tokens(content)
        lang_label = lang or "text"

        sep = manifest.output.separator.format(
            filepath=rel,
            tokens=f"{tokens:,}",
            chars=f"{len(content):,}",
            lang=lang_label,
        )
        parts.append(sep)
        parts.append(content)
        parts.append("")

    return "\n".join(parts)
