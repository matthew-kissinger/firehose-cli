"""Global settings and configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class OpenRouterConfig(BaseModel):
    api_key_env: str = "OPENROUTER_API_KEY"


class DefaultsConfig(BaseModel):
    models: list[str] = Field(default_factory=lambda: [
        "anthropic/claude-opus-4.6",
        "openai/gpt-5.4",
        "google/gemini-3.1-pro-preview",
    ])
    synthesis_model: str = "anthropic/claude-opus-4.6"
    max_concurrent: int = 5
    timeout_seconds: int = 600
    response_format: str = "markdown"
    max_tokens: int = 16384
    reasoning_effort: str = "high"


class ScanConfig(BaseModel):
    default_exclude: list[str] = Field(default_factory=lambda: [
        "**/*.test.*",
        "**/*.spec.*",
        "**/node_modules/**",
        "**/.git/**",
        "**/dist/**",
        "**/build/**",
        "**/*.lock",
        "**/*.map",
        "**/__pycache__/**",
        "**/.venv/**",
    ])


class FirehoseConfig(BaseModel):
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)


FIREHOSE_DIR = ".firehose"
MANIFEST_FILE = "manifest.yaml"
CONFIG_FILE = "config.yaml"
SNAPSHOTS_DIR = "snapshots"


def find_repo_root(start: Path) -> Path:
    """Walk up from start to find the git root. Falls back to start itself."""
    current = start.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return start.resolve()


def get_firehose_dir(root: Path | None = None) -> Path:
    """Get the .firehose directory, anchored at the repo root."""
    start = (root or Path.cwd()).resolve()
    repo_root = find_repo_root(start)
    return repo_root / FIREHOSE_DIR


def load_config(root: Path | None = None) -> FirehoseConfig:
    config_path = get_firehose_dir(root) / CONFIG_FILE
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return FirehoseConfig.model_validate(data)
    return FirehoseConfig()


def save_config(config: FirehoseConfig, root: Path | None = None) -> Path:
    fh_dir = get_firehose_dir(root)
    fh_dir.mkdir(parents=True, exist_ok=True)
    config_path = fh_dir / CONFIG_FILE
    with open(config_path, "w") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)
    return config_path


def get_api_key(config: FirehoseConfig | None = None) -> str:
    env_var = (config or FirehoseConfig()).openrouter.api_key_env
    key = os.environ.get(env_var, "")
    if not key:
        raise ValueError(
            f"OpenRouter API key not found.\n"
            f"  Set the {env_var} environment variable:\n"
            f"    export {env_var}=sk-or-v1-...\n"
            f"  Get a key at https://openrouter.ai/settings/keys"
        )
    return key
