"""Pydantic models for run metadata and comparison reports."""

from __future__ import annotations

from pydantic import BaseModel


class RunMeta(BaseModel):
    timestamp: str
    codebase_root: str
    total_files: int
    total_tokens_est: int
    models_requested: list[str]
    models_completed: int = 0
    models_failed: int = 0
    total_cost_usd: float = 0.0
    total_latency_max_ms: int = 0
    prompt_template: str = "analyze"
