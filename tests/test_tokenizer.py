"""Tests for the tokenizer module."""

from firehose.core.tokenizer import estimate_tokens, estimate_tokens_fast


def test_estimate_tokens():
    text = "Hello, world! This is a test."
    tokens = estimate_tokens(text)
    assert tokens > 0
    assert tokens < 20


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_fast():
    text = "a" * 400
    tokens = estimate_tokens_fast(text)
    assert tokens == 100


def test_estimate_tokens_fast_empty():
    assert estimate_tokens_fast("") == 0
