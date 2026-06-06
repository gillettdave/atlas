"""Phase D: application packages router under `/applications`."""
from __future__ import annotations


def test_applications_router_prefix() -> None:
    from app.api.application_packages import router

    assert router.prefix == "/applications"
