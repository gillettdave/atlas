"""`collector_pipeline._transient_http_error` classification."""

from __future__ import annotations

import httpx
import pytest

from app.services import collector_pipeline as capline


def _status_err(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://127.0.0.1:8000/health")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError("test", request=req, response=resp)


@pytest.mark.parametrize("code", [408, 425, 429, 500, 502, 503, 504])
def test_transient_http_status_errors(code: int) -> None:
    assert capline._transient_http_error(_status_err(code)) is True


@pytest.mark.parametrize("code", [400, 401, 404, 422])
def test_non_transient_http_status_errors(code: int) -> None:
    assert capline._transient_http_error(_status_err(code)) is False


def test_transient_connect_error() -> None:
    req = httpx.Request("GET", "http://127.0.0.1:9/nope")
    exc = httpx.ConnectError("refused", request=req)
    assert capline._transient_http_error(exc) is True


def test_transient_read_timeout() -> None:
    req = httpx.Request("GET", "http://127.0.0.1:8000/x")
    exc = httpx.ReadTimeout("slow", request=req)
    assert capline._transient_http_error(exc) is True


def test_transient_remote_protocol_error() -> None:
    req = httpx.Request("GET", "http://127.0.0.1:8000/x")
    exc = httpx.RemoteProtocolError("peer closed", request=req)
    assert capline._transient_http_error(exc) is True
