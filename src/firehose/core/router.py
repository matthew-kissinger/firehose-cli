"""OpenRouter fan-out - async dispatch to multiple LLMs."""

from __future__ import annotations

import asyncio
import time

import httpx
from openai import AsyncOpenAI

from firehose.config.settings import get_api_key, FirehoseConfig
from firehose.models.response import AnalysisReport, ModelResponse


def create_client(config: FirehoseConfig | None = None) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=get_api_key(config),
        default_headers={
            "HTTP-Referer": "https://github.com/mkissinger/firehose-cli",
            "X-Title": "Firehose CLI",
        },
    )


async def fire_model(
    client: AsyncOpenAI,
    model: str,
    payload: str,
    sem: asyncio.Semaphore,
    max_tokens: int = 16384,
    reasoning_effort: str = "high",
    timeout: int = 600,
    response_format: str = "markdown",
) -> ModelResponse:
    """Send payload to a single model and capture response."""
    provider = model.split("/")[0] if "/" in model else "unknown"

    # Cap max_tokens to provider limits (Gemini max is 65536)
    provider_max = {"google": 65536}
    max_tokens = min(max_tokens, provider_max.get(provider, max_tokens))

    async with sem:
        t0 = time.monotonic()
        try:
            extra_body: dict = {}

            # Use the correct OpenRouter reasoning parameter format
            if reasoning_effort and reasoning_effort != "none":
                extra_body["reasoning"] = {"effort": reasoning_effort}

            if response_format == "json":
                extra_body["response_format"] = {"type": "json_object"}

            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": payload}],
                    max_tokens=max_tokens,
                    extra_body=extra_body,
                ),
                timeout=timeout,
            )
            latency = int((time.monotonic() - t0) * 1000)

            choice = response.choices[0]
            raw = choice.message.content or ""

            # Extract generation ID for cost polling
            gen_id = getattr(response, "id", "") or ""

            # Parse JSON report if applicable
            report = None
            if response_format == "json":
                try:
                    import json
                    data = json.loads(raw)
                    report = AnalysisReport.model_validate(data)
                except (json.JSONDecodeError, Exception):
                    pass

            return ModelResponse(
                model=model,
                provider=provider,
                status="complete",
                latency_ms=latency,
                tokens_prompt=response.usage.prompt_tokens if response.usage else 0,
                tokens_completion=response.usage.completion_tokens if response.usage else 0,
                cost_usd=0.0,
                finish_reason=choice.finish_reason or "unknown",
                generation_id=gen_id,
                raw_response=raw,
                report=report,
            )

        except asyncio.TimeoutError:
            latency = int((time.monotonic() - t0) * 1000)
            return ModelResponse(
                model=model,
                provider=provider,
                status="timeout",
                latency_ms=latency,
                tokens_prompt=0,
                tokens_completion=0,
                cost_usd=0.0,
                finish_reason="timeout",
                generation_id="",
                raw_response="",
                error=f"Timed out after {timeout}s",
            )
        except Exception as e:
            latency = int((time.monotonic() - t0) * 1000)
            return ModelResponse(
                model=model,
                provider=provider,
                status="failed",
                latency_ms=latency,
                tokens_prompt=0,
                tokens_completion=0,
                cost_usd=0.0,
                finish_reason="error",
                generation_id="",
                raw_response="",
                error=str(e),
            )


async def get_generation_stats(gen_id: str, api_key: str) -> dict:
    """Poll OpenRouter generation stats endpoint for actual cost/token data."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://openrouter.ai/api/v1/generation?id={gen_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        return resp.json().get("data", {})


async def fire_all(
    models: list[str],
    payload: str,
    config: FirehoseConfig | None = None,
    max_concurrent: int = 5,
    max_tokens: int = 16384,
    reasoning_effort: str = "high",
    timeout: int = 600,
    response_format: str = "markdown",
) -> list[ModelResponse]:
    """Fan out to N models concurrently."""
    client = create_client(config)
    sem = asyncio.Semaphore(max_concurrent)

    tasks = [
        fire_model(
            client, model, payload, sem,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            timeout=timeout,
            response_format=response_format,
        )
        for model in models
    ]

    results = await asyncio.gather(*tasks)
    return list(results)
