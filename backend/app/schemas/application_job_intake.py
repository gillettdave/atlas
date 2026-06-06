"""`/applications/jobs/intake` — Phase E1+ (Jobr `POST /jobs/intake` parity)."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class ApplicationJobIntakeRequest(BaseModel):
    """Queue one listing through Atlas cleaner/importer (+ optional CRM track).

    Matches Jobr-era shape (`url`, `manual_text`, `source_name`) while mapping to
    canonical `jobs` instead of Jobr `Job`.
    """

    url: Optional[AnyHttpUrl] = Field(
        default=None,
        description="HTTP(S) job posting URL. Do not combine with manual_text.",
    )
    manual_text: Optional[str] = Field(
        default=None,
        max_length=500_000,
        description=(
            "Pasted JD or listing text alone. Synthesizes a deterministic "
            "`https://atlas.manual/{digest}` apply URL — do not combine with url."
        ),
    )
    source_name: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Recorded on `ingestion_runs.source_name` (manual paste labels).",
    )
    title_override: Optional[str] = Field(default=None, max_length=512)
    company_override: Optional[str] = Field(default=None, max_length=256)
    ingestion_source_id: Optional[uuid.UUID] = None
    then_process: bool = Field(
        default=True,
        description="Run cleaner/importer (`process_pending`) for this run.",
    )
    then_rescore: bool = Field(
        default=True,
        description="If canonical `job_id` exists after processing, rescored once.",
    )
    profile_slug: Optional[str] = Field(default=None, max_length=64)
    create_application_track: bool = Field(
        default=True,
        description=(
            "If a canonical job was produced/matched and no duplicate CRM row exists "
            "for tenant, attach `application_job_tracks`."
        ),
    )
    track_stage: str = Field(default="interested", max_length=64)
    track_notes: Optional[str] = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def _url_xor_text(self) -> ApplicationJobIntakeRequest:
        has_url = self.url is not None
        has_text = bool((self.manual_text or "").strip())
        if has_url == has_text:
            raise ValueError("Exactly one of url or manual_text (non-empty) is required.")
        return self


class ApplicationJobIntakeResponse(BaseModel):
    ingestion_run_id: uuid.UUID
    raw_event_id: uuid.UUID
    fetch_status: str
    parse_status: Optional[str] = None
    job_id: Optional[uuid.UUID] = None
    application_track_id: Optional[uuid.UUID] = None
    track_was_existing: bool = Field(
        default=False,
        description="True if `application_track_id` points at a pre-existing CRM row.",
    )

    model_config = ConfigDict(extra="forbid")
