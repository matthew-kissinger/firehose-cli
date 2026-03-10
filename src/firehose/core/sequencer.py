"""Dependency graph building and topological sort.

This module handles import resolution for supported languages
and produces a dependency-ordered sequence of files.
"""

from __future__ import annotations

import re
from pathlib import Path

# Import patterns per language (regex fallback - tree-sitter integration is future work)
IMPORT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "python": [
        re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE),
    ],
    "typescript": [
        re.compile(r"""(?:import|export)\s+.*?from\s+['"]([^'"]+)['"]""", re.MULTILINE),
        re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE),
    ],
    "javascript": [
        re.compile(r"""(?:import|export)\s+.*?from\s+['"]([^'"]+)['"]""", re.MULTILINE),
        re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE),
    ],
    "rust": [
        re.compile(r"^\s*(?:use|mod)\s+([\w:]+)", re.MULTILINE),
    ],
    "go": [
        re.compile(r'"([^"]+)"', re.MULTILINE),
    ],
    "java": [
        re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
    ],
}


def extract_imports(content: str, lang: str) -> list[str]:
    """Extract import specifiers from file content."""
    patterns = IMPORT_PATTERNS.get(lang, [])
    imports: list[str] = []
    for pat in patterns:
        imports.extend(pat.findall(content))
    return imports


def resolve_import_to_file(
    import_spec: str,
    source_file: Path,
    root: Path,
    file_set: set[str],
) -> str | None:
    """Try to resolve an import specifier to a file path relative to root.

    This is a best-effort heuristic for relative imports.
    """
    # Handle relative paths (./foo, ../foo)
    if import_spec.startswith("."):
        base = source_file.parent
        candidate_base = (base / import_spec).resolve()
        rel_base = str(candidate_base.relative_to(root)).replace("\\", "/")

        # Try common extensions
        for ext in ["", ".ts", ".tsx", ".js", ".jsx", ".py", "/index.ts", "/index.js"]:
            candidate = rel_base + ext
            if candidate in file_set:
                return candidate

    # Handle Python dotted imports
    if "." in import_spec and "/" not in import_spec:
        parts = import_spec.split(".")
        candidate = "/".join(parts) + ".py"
        if candidate in file_set:
            return candidate
        # Try as package
        candidate = "/".join(parts) + "/__init__.py"
        if candidate in file_set:
            return candidate

    return None


def build_dependency_graph(
    files: list[tuple[str, str | None, str]],
    root: Path,
) -> dict[str, list[str]]:
    """Build adjacency list: file -> [files it imports].

    Args:
        files: list of (relative_path, language, content) tuples
        root: codebase root
    """
    file_set = {rel for rel, _, _ in files}
    graph: dict[str, list[str]] = {rel: [] for rel, _, _ in files}

    for rel, lang, content in files:
        if lang is None:
            continue
        imports = extract_imports(content, lang)
        source_path = root / rel
        for imp in imports:
            resolved = resolve_import_to_file(imp, source_path, root, file_set)
            if resolved and resolved != rel:
                graph[rel].append(resolved)

    return graph


def topological_sort(graph: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm on reversed graph so dependencies come first.

    graph[a] = [b] means "a imports b", so b should appear before a.
    We reverse the edges and do standard Kahn's.
    """
    # Build reverse graph: out_degree in original = in_degree in reversed
    reverse: dict[str, list[str]] = {node: [] for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep in reverse:
                reverse[dep].append(node)

    # in_degree in original graph = number of things each node imports
    # But we want: nodes with no *importers* (nothing depends on them) last
    # Actually: in reversed graph, in_degree = number of deps in original
    in_degree: dict[str, int] = {node: 0 for node in graph}
    for node, deps in graph.items():
        for dep in deps:
            if dep in in_degree:
                pass
        # Count how many things import this node
    for node in graph:
        in_degree[node] = 0
    for node, importers in reverse.items():
        in_degree[node] = len(importers)

    # Nodes with no importers (leaves - nobody imports them) go last
    # Nodes that are imported by many go first (they are dependencies)
    # Use reversed Kahn's: start with nodes that have no deps
    dep_count: dict[str, int] = {node: len(deps) for node, deps in graph.items()}
    queue = sorted([n for n, d in dep_count.items() if d == 0])
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        # For each node that imports this one, decrement its dep count
        for importer in sorted(reverse.get(node, [])):
            dep_count[importer] -= 1
            if dep_count[importer] == 0:
                queue.append(importer)
                queue.sort()

    # Remaining nodes are in cycles - append alphabetically
    remaining = sorted(set(graph) - set(result))
    result.extend(remaining)

    return result
