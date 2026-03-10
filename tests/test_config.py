"""Tests for config/settings module."""

import tempfile
from pathlib import Path

from firehose.config.settings import (
    FirehoseConfig,
    get_firehose_dir,
    load_config,
    save_config,
)


def test_default_config():
    config = FirehoseConfig()
    assert config.openrouter.api_key_env == "OPENROUTER_API_KEY"
    assert config.defaults.max_concurrent == 5
    assert config.defaults.timeout_seconds == 600
    assert config.defaults.max_tokens == 16384
    assert len(config.defaults.models) == 3


def test_save_and_load_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = FirehoseConfig()
        save_config(config, root)

        loaded = load_config(root)
        assert loaded.defaults.max_concurrent == config.defaults.max_concurrent
        assert loaded.defaults.models == config.defaults.models


def test_get_firehose_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "myproject"
        root.mkdir()
        # No .git, so repo root falls back to the dir itself
        result = get_firehose_dir(root)
        assert result == root.resolve() / ".firehose"


def test_load_config_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(root)
        # Should return defaults
        assert config.defaults.max_concurrent == 5
