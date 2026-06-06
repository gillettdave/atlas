"""`collector_pipeline._retry_api` — backoff loop (settings + asyncio.sleep patched)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.services import collector_pipeline as capline


@pytest.fixture
def fast_pipeline_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tiny limits and no real sleep so tests stay fast."""

    fake = SimpleNamespace(
        collector_pipeline_http_max_attempts=5,
        collector_pipeline_http_base_seconds=0.001,
        collector_pipeline_http_max_wait_seconds=0.01,
    )
    monkeypatch.setattr("app.services.collector_pipeline.get_settings", lambda: fake)

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("app.services.collector_pipeline.asyncio.sleep", no_sleep)


def test_retry_api_returns_after_transient_failures(
    fast_pipeline_retry: None,
) -> None:
    req = httpx.Request("GET", "http://127.0.0.1/health")
    n = {"c": 0}

    async def coro() -> str:
        n["c"] += 1
        if n["c"] < 3:
            raise httpx.ConnectError("refused", request=req)
        return "ok"

    out = asyncio.run(capline._retry_api("test_op", coro))
    assert out == "ok"
    assert n["c"] == 3


def test_retry_api_non_transient_raises_immediately(
    fast_pipeline_retry: None,
) -> None:
    req = httpx.Request("GET", "http://127.0.0.1/x")
    resp = httpx.Response(400, request=req)
    n = {"c": 0}

    async def coro() -> None:
        n["c"] += 1
        raise httpx.HTTPStatusError("bad", request=req, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(capline._retry_api("bad_op", coro))
    assert n["c"] == 1


def test_retry_api_exhausts_attempts(fast_pipeline_retry: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(
        collector_pipeline_http_max_attempts=3,
        collector_pipeline_http_base_seconds=0.001,
        collector_pipeline_http_max_wait_seconds=0.01,
    )
    monkeypatch.setattr("app.services.collector_pipeline.get_settings", lambda: fake)

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("app.services.collector_pipeline.asyncio.sleep", no_sleep)

    req = httpx.Request("GET", "http://127.0.0.1/health")
    n = {"c": 0}

    async def coro() -> None:
        n["c"] += 1
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(httpx.ConnectError):
        asyncio.run(capline._retry_api("flaky", coro))
    assert n["c"] == 3
