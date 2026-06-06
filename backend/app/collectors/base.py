"""Collector base types.

A collector yields RawCollectedRecord instances. A SourceRow is one line
from the input CSV describing a company to collect from.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SourceRow:
    """One row from the input CSV describing a company to collect."""
    company_name: str
    source: str = ""
    profile_url: str = ""
    official_site: str = ""
    jobs_page: str = ""
    ats_type: str = ""
    ats_board_url: str = ""
    ats_slug: str = ""
    cryptojobslist_fallback_jobs_page: str = ""
    resolution_type: str = ""
    notes: str = ""


@dataclass
class RawCollectedRecord:
    """A single raw job record emitted by a collector.

    Shape matches the backend `RawJobEventCreate` schema so the runner can
    submit it unchanged.
    """
    provider: str
    source_url: str
    raw_payload: dict[str, Any]
    raw_html: Optional[str] = None
    fetch_status: str = "fetched"

    def to_api_payload(self) -> dict[str, Any]:
        d = asdict(self)
        if d["raw_html"] is None:
            d.pop("raw_html")
        return d


@dataclass
class CollectionStats:
    """Per-source stats surfaced by the runner."""
    sources_attempted: int = 0
    sources_with_records: int = 0
    sources_failed: int = 0
    records_collected: int = 0
    by_provider: dict[str, int] = field(default_factory=dict)
    failures: list[dict[str, str]] = field(default_factory=list)

    def record(self, provider: str) -> None:
        self.by_provider[provider] = self.by_provider.get(provider, 0) + 1
        self.records_collected += 1

    def fail(self, company: str, source_url: str, reason: str) -> None:
        self.sources_failed += 1
        self.failures.append({
            "company": company,
            "source_url": source_url,
            "reason": reason,
        })
