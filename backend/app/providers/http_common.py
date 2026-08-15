"""Shared HTTP plumbing for provider connectors.

One pooled httpx.AsyncClient per process; JSON post with timeout mapping into
typed :class:`ProviderError`; SSE event parsing for streaming adapters.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.providers.base import ErrorType, ProviderError


def build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=10.0),
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        follow_redirects=False,
        http2=True,
    )


async def shared_request(
    client: httpx.AsyncClient | None,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict | None = None,
    timeout: float,
    provider: str,
) -> httpx.Response:
    """Perform a request, mapping transport failures to typed errors."""
    try:
        if client is not None:
            resp = await client.request(
                method, url, headers=headers, json=json, timeout=timeout
            )
        else:
            async with build_client() as c:
                resp = await c.request(method, url, headers=headers, json=json, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderError(
            ErrorType.TIMEOUT, f"{provider}: request timed out after {timeout}s", provider=provider
        ) from exc
    except httpx.ConnectError as exc:
        raise ProviderError(
            ErrorType.PROVIDER_DOWN,
            f"{provider}: cannot reach endpoint",
            provider=provider,
        ) from exc
    return resp


async def raise_for_provider_error(
    resp: httpx.Response, adapter: object, provider: str
) -> None:
    """Map non-2xx responses into typed ProviderError via the adapter."""
    if resp.status_code < 300:
        return
    body: dict | None = None
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        pass
    error_type = adapter.map_error(resp.status_code, body, resp.headers)
    message = f"{provider}: HTTP {resp.status_code}"
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            message += f" [{err.get('type') or err.get('code') or err.get('message', '')}]"
        elif isinstance(err, str):
            message += f" [{err[:160]}]"
        else:
            msg = body.get("message")
            if isinstance(msg, str):
                message += f" [{msg[:160]}]"
    raise ProviderError(
        error_type,
        message,
        provider=provider,
        status_code=resp.status_code,
        retry_after=adapter._extract_retry_after(resp.headers),
    )


async def iter_sse(response: httpx.Response) -> AsyncIterator[dict]:
    """Yield parsed ``data:`` JSON events from an SSE response."""
    import json as _json

    async for line in response.aiter_lines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                break
            try:
                yield _json.loads(payload)
            except _json.JSONDecodeError:
                continue
