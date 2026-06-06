"""SQLAlchemy ORM models for Project Atlas.

All tables required by the canonical schema live here.
Import order matters for Alembic metadata discovery — every model class
must be imported by this module.
"""
from .base import Base
from .user import User
from .ingestion_run import IngestionRun
from .ingestion_source import IngestionSource
from .application_job_track import ApplicationJobTrack
from .application_package import ApplicationPackage
from .raw_job_event import RawJobEvent
from .job import Job
from .job_source_sighting import JobSourceSighting
from .job_score import JobScore
from .digest import Digest
from .digest_item import DigestItem
from .pipeline_event import PipelineEvent
from .career_memory import (
    CareerDiscoveryProfile,
    CareerDocument,
    CareerEvidenceChunk,
    CareerFact,
    CareerProfileAnswer,
    CareerProfileQuestion,
    CareerTimelineEntry,
)
from .user_profile import UserProfile
from .delivery_schedule import DeliverySchedule
from .job_feedback import JobFeedback
from .collector_schedule import CollectorSchedule
from .user_qualification_settings import UserQualificationSettings
from .discovery_seed import DiscoverySeed
from .discovery_event import DiscoveryEvent
from .email_sync import EmailSyncSource, EmailSyncEvent
from .candidate_profile import CandidateProfile

__all__ = [
    "Base",
    "User",
    "CareerDocument",
    "CareerEvidenceChunk",
    "CareerFact",
    "CareerTimelineEntry",
    "CareerDiscoveryProfile",
    "CareerProfileQuestion",
    "CareerProfileAnswer",
    "ApplicationJobTrack",
    "ApplicationPackage",
    "IngestionRun",
    "RawJobEvent",
    "Job",
    "JobSourceSighting",
    "JobScore",
    "Digest",
    "DigestItem",
    "PipelineEvent",
    "UserProfile",
    "DeliverySchedule",
    "JobFeedback",
    "CollectorSchedule",
    "IngestionSource",
    "UserQualificationSettings",
    "DiscoverySeed",
    "DiscoveryEvent",
    "EmailSyncSource",
    "EmailSyncEvent",
    "CandidateProfile",
]
