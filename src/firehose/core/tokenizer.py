"""Token estimation utilities using tiktoken."""

from __future__ import annotations

import tiktoken

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def estimate_tokens(text: str) -> int:
    return len(_get_encoder().encode(text))


def estimate_tokens_fast(text: str) -> int:
    """Rough estimate without tokenizing - ~4 chars per token."""
    return len(text) // 4
