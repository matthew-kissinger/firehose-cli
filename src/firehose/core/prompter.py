"""Analysis prompt construction."""

from __future__ import annotations

from pathlib import Path

# Default prompt lives alongside this module
_PROMPTS_DIR = Path(__file__).parent.parent / "config" / "prompts"


def load_prompt(prompt_path: str | Path | None = None) -> str:
    """Load the analysis prompt from a file or return the default."""
    if prompt_path is not None:
        path = Path(prompt_path)
        if path.is_file():
            return path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Prompt file not found: {path}")

    default = _PROMPTS_DIR / "analyze.md"
    return default.read_text(encoding="utf-8")


def build_payload(prompt: str, flat_content: str) -> str:
    """Combine analysis prompt with flattened codebase into the final payload."""
    return f"{prompt}\n\n{flat_content}"
