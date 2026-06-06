"""Resilient HTTP helpers for ATS collectors (Sprint M.4).

Retry with backoff on transient responses and numeric ``Retry-After`` when present.
"""

from __future__ import annotations

import logging
import random
import time
from email.utils import parsedate_to_datetime

import requests

from ..config import get_settings

log = logging.getLogger(__name__)

_RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _parse_retry_after_seconds(resp: requests.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return min(float(raw), 120.0)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt is None:
            return None
        import datetime as _dt

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        now = _dt.datetime.now(dt.tzinfo)
        delay = (dt - now).total_seconds()
        if delay <= 0:
            return None
        return min(delay, 120.0)
    except (TypeError, ValueError, OverflowError):
        return None


def _backoff_sleep(
    attempt: int,
    resp: requests.Response | None,
    *,
    base: float,
    cap: float,
) -> float:
    if resp is not None:
        parsed = _parse_retry_after_seconds(resp)
        if parsed is not None:
            return parsed + random.uniform(0.0, min(parsed * 0.15, 2.0))
    exp = min(cap, base * (2**attempt))
    return exp + random.uniform(0.0, min(exp * 0.25, 3.5))


def http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, object] | None = None,
    timeout: float | tuple[float, float] | None = None,
    max_attempts: int | None = None,
) -> tuple[requests.Response | None, str]:
    """GET with backoff on 429/transient failures. Returns `(response, '')` on OK."""

    s = get_settings()
    attempts = max(1, max_attempts if max_attempts is not None else s.http_retry_max_attempts)
    to = timeout if timeout is not None else (s.http_timeout_connect_seconds, s.http_timeout_read_seconds)

    last_resp: requests.Response | None = None
    last_err = "unknown_error"

    for attempt in range(attempts):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=to)
            last_resp = resp

            if resp.status_code < 400:
                return resp, ""

            if resp.status_code in _RETRY_STATUS:
                last_err = f"http_{resp.status_code}_attempt_{attempt + 1}"
                if attempt < attempts - 1:
                    wa = _backoff_sleep(attempt, resp, base=s.http_retry_base_seconds, cap=s.http_retry_max_backoff_seconds)
                    log.warning(
                        "http_get retry URL=%s status=%s sleep=%.2fs attempt=%s",
                        url[:180],
                        resp.status_code,
                        wa,
                        attempt + 1,
                    )
                    time.sleep(wa)
                    continue
                return resp, f"http_{resp.status_code}_exhausted"

            # Non-retry terminal (4xx other than specials, ...)
            return resp, f"http_{resp.status_code}"

        except requests.Timeout:
            last_err = "timeout"
            last_resp = None
            if attempt < attempts - 1:
                wa = _backoff_sleep(attempt, None, base=s.http_retry_base_seconds, cap=s.http_retry_max_backoff_seconds)
                time.sleep(wa)
                continue
            return None, last_err

        except requests.RequestException as e:
            last_err = f"connection:{type(e).__name__}"
            last_resp = None
            if attempt < attempts - 1:
                wa = _backoff_sleep(attempt, None, base=s.http_retry_base_seconds, cap=s.http_retry_max_backoff_seconds)
                time.sleep(wa)
                continue
            return None, last_err

    return last_resp, last_err


def json_from_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, object] | None = None,
    timeout: float | tuple[float, float] | None = None,
) -> tuple[object | None, str]:
    resp, tag = http_get(url, headers=headers, params=params, timeout=timeout)
    if resp is None:
        return None, tag
    if not resp.ok:
        return None, tag or f"http_{resp.status_code}"
    try:
        data = resp.json()
    except ValueError:
        return None, "bad_json_body"
    return data, ""
