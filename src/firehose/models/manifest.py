"""Pydantic models for the .firehose/manifest.yaml schema."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class LanguageStats(BaseModel):
    files: int
    tokens: int


class ManifestMeta(BaseModel):
    total_files: int = 0
    total_tokens_est: int = 0
    total_chars: int = 0
    languages: dict[str, LanguageStats] = {}
    entrypoints_detected: list[str] = []
    unreachable_files: list[str] = []


class StripConfig(BaseModel):
    comments: bool = True
    whitespace: Literal["aggressive", "moderate", "none"] = "aggressive"
    imports: bool = False


class DocsConfig(BaseModel):
    include: bool = True
    trust_level: Literal["unverified", "trusted"] = "unverified"
    files: list[str] = []
    exclude: list[str] = []


class OutputConfig(BaseModel):
    separator: str = "--- {filepath} [tokens: ~{tokens}, chars: {chars}, lang: {lang}] ---"
    file_tree: bool = True
    metadata_header: bool = True


class SequenceNode(BaseModel):
    """Recursive node: either a leaf (file path/glob) or a named group with children."""

    # Leaf (file)
    path: str | None = None

    # Branch (group)
    name: str | None = None
    order: Literal["dependency", "manual", "alphabetical"] = "dependency"
    collapse: bool = False
    children: list[SequenceNode] = []

    def is_leaf(self) -> bool:
        return self.path is not None

    def is_group(self) -> bool:
        return self.name is not None and len(self.children) > 0


class Manifest(BaseModel):
    version: int = 1
    generated: str = ""
    root: str = "."
    meta: ManifestMeta = Field(default_factory=ManifestMeta)
    exclude: list[str] = Field(default_factory=lambda: [
        "**/*.test.*",
        "**/*.spec.*",
        "**/fixtures/**",
        "**/node_modules/**",
        "**/.git/**",
        "**/dist/**",
        "**/build/**",
        "**/*.lock",
        "**/*.map",
        "**/__pycache__/**",
        "**/.venv/**",
    ])
    strip: StripConfig = Field(default_factory=StripConfig)
    docs: DocsConfig = Field(default_factory=DocsConfig)
    sequence: list[SequenceNode] = []
    output: OutputConfig = Field(default_factory=OutputConfig)
