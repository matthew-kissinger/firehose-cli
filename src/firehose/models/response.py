"""Pydantic models for model responses and analysis reports."""

from __future__ import annotations

from pydantic import BaseModel
from typing import Literal


class AnalysisReport(BaseModel):
    """Only used when --response-format json is specified."""

    consultation: str
    files_referenced: list[str] = []
    key_concerns: list[str] = []
    key_strengths: list[str] = []


class ModelResponse(BaseModel):
    model: str
    provider: str
    status: Literal["complete", "failed", "timeout"]
    latency_ms: int
    tokens_prompt: int
    tokens_completion: int
    cost_usd: float
    finish_reason: str
    generation_id: str
    raw_response: str
    report: AnalysisReport | None = None
    error: str | None = None
