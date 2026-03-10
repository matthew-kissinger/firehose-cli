"""Tests for the sequencer module."""

from firehose.core.sequencer import (
    extract_imports,
    topological_sort,
)


def test_extract_imports_python():
    code = "import os\nfrom pathlib import Path\nimport json\n"
    imports = extract_imports(code, "python")
    assert "os" in imports
    assert "pathlib" in imports
    assert "json" in imports


def test_extract_imports_typescript():
    code = """import { foo } from './foo';\nimport bar from '../bar';\nconst x = require('baz');\n"""
    imports = extract_imports(code, "typescript")
    assert "./foo" in imports
    assert "../bar" in imports
    assert "baz" in imports


def test_extract_imports_unknown_lang():
    code = "import something\n"
    imports = extract_imports(code, "unknown_lang")
    assert imports == []


def test_topological_sort_simple():
    graph = {
        "a.py": ["b.py"],
        "b.py": ["c.py"],
        "c.py": [],
    }
    result = topological_sort(graph)
    assert result.index("c.py") < result.index("b.py")
    assert result.index("b.py") < result.index("a.py")


def test_topological_sort_no_deps():
    graph = {
        "a.py": [],
        "b.py": [],
        "c.py": [],
    }
    result = topological_sort(graph)
    assert sorted(result) == ["a.py", "b.py", "c.py"]


def test_topological_sort_cycle():
    graph = {
        "a.py": ["b.py"],
        "b.py": ["a.py"],
    }
    result = topological_sort(graph)
    # Both should appear even with a cycle
    assert set(result) == {"a.py", "b.py"}
