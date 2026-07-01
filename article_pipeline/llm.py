"""LLM calling utilities for article pipeline.

Provides a unified interface for calling LLMs via Anthropic-compatible API.
Used by synthesis, outline, style, prosody, and writer layers.
"""

import os
import requests
import time
from article_pipeline.config import load_config


def get_api_key() -> str | None:
    """Get API key from environment variables."""
    return (os.environ.get("AP_DS_API_KEY") or
            os.environ.get("DEEPSEEK_API_KEY") or
            os.environ.get("ANTHROPIC_API_KEY") or
            os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def call_messages_api(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float | None = None,
) -> dict:
    """Call Anthropic-compatible /v1/messages API.

    Args:
        base_url: API base URL (e.g. "https://api.anthropic.com")
        api_key: API key
        model: Model name
        system_prompt: System prompt
        user_prompt: User prompt
        max_tokens: Max tokens to generate
        temperature: Sampling temperature

    Returns:
        {"content": str, "model": str, "tokens": dict} on success
        {"error": str, "message": str} on failure
    """
    max_retries = 3
    backoff = [5, 15, 45]

    for attempt in range(max_retries + 1):
        try:
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}]
            }
            if temperature is not None:
                payload["temperature"] = temperature

            resp = requests.post(
                f"{base_url}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=180
            )

            # Don't retry 4xx client errors (except 429)
            if resp.status_code == 429:
                if attempt < max_retries:
                    wait = backoff[attempt]
                    print(f"  [llm] Rate limited (429), retrying in {wait}s ({attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
            elif 400 <= resp.status_code < 500:
                return {"error": "client_error",
                        "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}

            resp.raise_for_status()
            data = resp.json()

            # Extract text content
            text_parts = []
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = "\n".join(text_parts)

            return {
                "content": content,
                "model": data.get("model", model),
                "tokens": data.get("usage", {})
            }

        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < max_retries:
                wait = backoff[attempt]
                print(f"  [llm] {type(e).__name__}, retrying in {wait}s ({attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            return {"error": "api_unreachable" if isinstance(e, requests.ConnectionError) else "api_timeout",
                    "message": str(e)}

        except requests.RequestException as e:
            return {"error": "request_failed", "message": str(e)}

    return {"error": "max_retries_exceeded"}


def call_with_fallback(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float | None = None,
) -> dict:
    """Try primary API, then fallback APIs.

    Reads endpoints from ~/.config/article-pipeline/config.yaml under "deepseek" key.
    Default endpoints:
    1. z.ai + claude-sonnet-4 (writing model)
    2. z.ai + glm-5.1
    3. deepseek.com + deepseek-v4-pro

    Args:
        system_prompt: System prompt
        user_prompt: User prompt
        max_tokens: Max tokens
        temperature: Sampling temperature

    Returns:
        Same as call_messages_api
    """
    config = load_config()
    ds = config.get("deepseek", {})
    api_key = get_api_key()

    if not api_key:
        return {"error": "missing_api_key",
                "message": "Set AP_DS_API_KEY, DEEPSEEK_API_KEY, or ANTHROPIC_API_KEY"}

    if temperature is None:
        temperature = ds.get("temperature")

    endpoints = [
        (ds.get("base_url", "https://api.z.ai/api/anthropic"),
         ds.get("writing_model", "claude-sonnet-4-20250514")),
        (ds.get("base_url", "https://api.z.ai/api/anthropic"),
         ds.get("model", "glm-5.1")),
        (ds.get("fallback_url", "https://api.deepseek.com/anthropic"),
         ds.get("fallback_model", "deepseek-v4-pro")),
    ]

    for base_url, model in endpoints:
        if not base_url or not model:
            continue
        result = call_messages_api(base_url, api_key, model,
                                    system_prompt, user_prompt, max_tokens,
                                    temperature=temperature)
        if "error" not in result:
            return result

    return result  # Return last error


__all__ = ["call_messages_api", "call_with_fallback", "get_api_key"]
