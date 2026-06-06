"""`services.scheduler._delivery_build_retryable` — transient classification."""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from app.services import scheduler as sched


def test_build_retryable_database_operational() -> None:
    assert sched._delivery_build_retryable(OperationalError("statement timeout", None, None))


def test_build_retryable_timeout_family() -> None:
    assert sched._delivery_build_retryable(TimeoutError())


def test_build_retryable_connection_substring() -> None:
    assert sched._delivery_build_retryable(
        RuntimeError("connection reset by peer pool flush")
    )


def test_build_not_retryable_value_error() -> None:
    assert not sched._delivery_build_retryable(ValueError("bad digest config"))


def test_build_not_retryable_plain_message() -> None:
    assert not sched._delivery_build_retryable(RuntimeError("no such job row"))
