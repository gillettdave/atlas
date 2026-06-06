"""Atlas collectors.

Collectors fetch + parse provider pages and yield raw structured records.
They do NOT dedupe. They do NOT write CSVs. They do NOT talk to the DB
directly. A runner (scripts/collector_runner.py) drives a collector and
POSTs raw records to /collectors/raw-events.
"""
from .base import RawCollectedRecord, SourceRow

__all__ = ["RawCollectedRecord", "SourceRow"]
