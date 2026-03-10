"""Global settings and configuration loading."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import yaml
from platformdirs import user_config_dir
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
    max_tokens: int = 128000
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


def get_user_config_dir() -> Path:
    """Return the user-level config directory for firehose."""
    return Path(user_config_dir("firehose", appauthor=False))


def get_credentials_path() -> Path:
    """Return the path to the credentials file."""
    return get_user_config_dir() / "credentials"


def load_credentials() -> dict[str, str]:
    """Read key=value pairs from the credentials file."""
    creds_path = get_credentials_path()
    if not creds_path.exists():
        return {}
    result = {}
    for line in creds_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def save_credentials(creds: dict[str, str]) -> Path:
    """Write credentials to the user config dir with restrictive permissions."""
    creds_path = get_credentials_path()
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(f"{k}={v}" for k, v in creds.items()) + "\n"
    creds_path.write_text(content, encoding="utf-8")
    try:
        creds_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:
        pass  # Windows may not support Unix permissions
    return creds_path


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


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
    # Start with user-level config
    user_config_path = get_user_config_dir() / CONFIG_FILE
    data: dict = {}
    if user_config_path.exists():
        with open(user_config_path) as f:
            data = yaml.safe_load(f) or {}

    # Overlay project-level config
    config_path = get_firehose_dir(root) / CONFIG_FILE
    if config_path.exists():
        with open(config_path) as f:
            project_data = yaml.safe_load(f) or {}
        data = _deep_merge(data, project_data)

    return FirehoseConfig.model_validate(data) if data else FirehoseConfig()


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
    if key:
        return key

    # Fall back to credentials file
    creds = load_credentials()
    key = creds.get(env_var, "")
    if key:
        return key

    raise ValueError(
        f"OpenRouter API key not found.\n"
        f"  Option 1: Run 'firehose auth' to store your key\n"
        f"  Option 2: Set the {env_var} environment variable:\n"
        f"    export {env_var}=sk-or-v1-...\n"
        f"  Get a key at https://openrouter.ai/settings/keys"
    )
