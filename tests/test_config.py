"""Tests for config/settings module."""

import tempfile
from pathlib import Path

from firehose.config.settings import (
    FirehoseConfig,
    get_firehose_dir,
    load_config,
    load_credentials,
    save_config,
    save_credentials,
    get_api_key,
    get_credentials_path,
    _deep_merge,
)


def test_default_config():
    config = FirehoseConfig()
    assert config.openrouter.api_key_env == "OPENROUTER_API_KEY"
    assert config.defaults.max_concurrent == 5
    assert config.defaults.timeout_seconds == 600
    assert config.defaults.max_tokens == 128000
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


def test_credentials_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "firehose.config.settings.get_user_config_dir", lambda: tmp_path
    )
    creds = {"OPENROUTER_API_KEY": "sk-or-v1-test123"}
    save_credentials(creds)
    loaded = load_credentials()
    assert loaded["OPENROUTER_API_KEY"] == "sk-or-v1-test123"


def test_credentials_ignores_comments_and_blanks(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "firehose.config.settings.get_user_config_dir", lambda: tmp_path
    )
    creds_path = tmp_path / "credentials"
    creds_path.write_text(
        "# comment\n\nOPENROUTER_API_KEY=sk-test\nEXTRA=val\n",
        encoding="utf-8",
    )
    loaded = load_credentials()
    assert loaded == {"OPENROUTER_API_KEY": "sk-test", "EXTRA": "val"}


def test_get_api_key_env_beats_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "firehose.config.settings.get_user_config_dir", lambda: tmp_path
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    save_credentials({"OPENROUTER_API_KEY": "from-file"})
    assert get_api_key() == "from-env"


def test_get_api_key_falls_back_to_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "firehose.config.settings.get_user_config_dir", lambda: tmp_path
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    save_credentials({"OPENROUTER_API_KEY": "from-file"})
    assert get_api_key() == "from-file"


def test_get_api_key_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "firehose.config.settings.get_user_config_dir", lambda: tmp_path
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        get_api_key()
        assert False, "Should have raised"
    except ValueError as e:
        assert "firehose auth" in str(e)


def test_deep_merge():
    base = {"a": 1, "b": {"x": 10, "y": 20}}
    override = {"b": {"y": 99, "z": 30}, "c": 3}
    result = _deep_merge(base, override)
    assert result == {"a": 1, "b": {"x": 10, "y": 99, "z": 30}, "c": 3}


def test_load_config_merges_user_and_project(tmp_path, monkeypatch):
    import yaml

    # Set up user-level config
    user_dir = tmp_path / "user_config"
    user_dir.mkdir()
    monkeypatch.setattr(
        "firehose.config.settings.get_user_config_dir", lambda: user_dir
    )
    user_config = {"defaults": {"max_concurrent": 10, "timeout_seconds": 300}}
    (user_dir / "config.yaml").write_text(yaml.dump(user_config), encoding="utf-8")

    # Set up project-level config (overrides max_concurrent)
    project_root = tmp_path / "project"
    project_root.mkdir()
    fh_dir = project_root / ".firehose"
    fh_dir.mkdir()
    project_config = {"defaults": {"max_concurrent": 3}}
    (fh_dir / "config.yaml").write_text(yaml.dump(project_config), encoding="utf-8")

    config = load_config(project_root)
    assert config.defaults.max_concurrent == 3  # project wins
    assert config.defaults.timeout_seconds == 300  # user-level preserved
