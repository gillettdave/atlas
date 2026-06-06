"""Full-pipeline retry eligibility (`collector_scheduler._collector_schedule_pipeline_retryable`)."""

from __future__ import annotations

import uuid

import pytest

from app.services import collector_scheduler as cs
from app.services.collector_pipeline import CollectorPipelineResult


def _res(
    *,
    ok: bool = False,
    error: str | None = "err",
    ingestion_run_id: uuid.UUID | None = None,
) -> CollectorPipelineResult:
    return CollectorPipelineResult(
        ok=ok,
        error=error,
        ingestion_run_id=ingestion_run_id,
    )


@pytest.mark.parametrize(
    "error_text",
    [
        "Server error '503'",
        "HTTPStatusError: 502",
        "status 504",
        "too many requests 429",
        "ConnectError",
        "connection refused",
        "ReadTimeout",
        "ReadError",
        "RemoteProtocolError",
        "PoolTimeout",
        "temporary failure",
        "Service Unavailable",
    ],
)
def test_retryable_transient_messages(error_text: str) -> None:
    assert cs._collector_schedule_pipeline_retryable(_res(error=error_text)) is True


@pytest.mark.parametrize(
    "error_text",
    [
        "input_csv not found",
        "No such file",
        "validation failed",
        "bad csv",
    ],
)
def test_not_retryable_operational_errors(error_text: str) -> None:
    assert cs._collector_schedule_pipeline_retryable(_res(error=error_text)) is False


def test_not_retryable_when_success() -> None:
    assert cs._collector_schedule_pipeline_retryable(_res(ok=True, error=None)) is False


def test_not_retryable_when_failure_but_no_message() -> None:
    assert cs._collector_schedule_pipeline_retryable(_res(ok=False, error=None)) is False


def test_not_retryable_when_ingestion_run_already_opened() -> None:
    rid = uuid.uuid4()
    assert (
        cs._collector_schedule_pipeline_retryable(
            _res(error="ConnectError foo", ingestion_run_id=rid)
        )
        is False
    )
