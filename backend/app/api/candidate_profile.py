"""GET/PUT /candidate-profile — personal contact info for resume generation."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from ..models.candidate_profile import CandidateProfile
from .deps import DbSession, TenantUserId
from ..models.base import utcnow

router = APIRouter(prefix="/candidate-profile", tags=["candidate-profile"])


class CandidateProfileSchema(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    website_url: str | None = None
    headline: str | None = None
    summary: str | None = None

    # Location search (Phase 1)
    home_city: str | None = None
    home_lat: float | None = None
    home_lng: float | None = None
    search_radius_km: int = 50
    target_cities: list[str] | None = None
    search_mode: str = "remote"

    class Config:
        from_attributes = True


class CandidateProfileResponse(CandidateProfileSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=CandidateProfileResponse | None)
def get_candidate_profile(db: DbSession, tenant_id: TenantUserId):
    row = db.query(CandidateProfile).filter_by(user_id=tenant_id).first()
    return row


@router.put("", response_model=CandidateProfileResponse)
def upsert_candidate_profile(
    payload: CandidateProfileSchema,
    db: DbSession,
    tenant_id: TenantUserId,
):
    row = db.query(CandidateProfile).filter_by(user_id=tenant_id).first()
    if row is None:
        row = CandidateProfile(id=uuid.uuid4(), user_id=tenant_id, created_at=utcnow(), updated_at=utcnow())
        db.add(row)

    for field, value in payload.model_dump(exclude_unset=False).items():
        setattr(row, field, value)
    row.updated_at = utcnow()

    db.commit()
    db.refresh(row)
    return row
