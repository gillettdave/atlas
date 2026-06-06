"""API routers."""
from fastapi import APIRouter

from . import (
    application_dashboard,
    application_job_intake,
    application_job_tracks,
    application_packages,
    auth,
    candidate_profile,
    career_memory,
    collector_schedules,
    collectors,
    digests,
    discovery,
    email_intake_route,
    feedback,
    imports,
    jobs,
    pipeline,
    pipeline_operator,
    profiles,
    qualification,
    schedules,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(application_job_intake.router)
api_router.include_router(application_job_tracks.router)
api_router.include_router(application_packages.router)
api_router.include_router(
    application_dashboard.router,
    prefix="/applications",
    tags=["applications-dashboard"],
)
api_router.include_router(collectors.router, prefix="/collectors", tags=["collectors"])
api_router.include_router(
    collector_schedules.router, prefix="/collector-schedules", tags=["collector-schedules"]
)
api_router.include_router(imports.router, prefix="/imports", tags=["imports"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(career_memory.router, prefix="")
api_router.include_router(digests.router, prefix="/digests", tags=["digests"])
api_router.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])
api_router.include_router(
    pipeline_operator.router, prefix="/pipeline", tags=["pipeline-operator"]
)
api_router.include_router(profiles.router, prefix="/profiles", tags=["profiles"])
api_router.include_router(schedules.router, prefix="/schedules", tags=["schedules"])
api_router.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
api_router.include_router(
    qualification.router, prefix="/qualification", tags=["qualification"]
)
api_router.include_router(candidate_profile.router)
api_router.include_router(discovery.router)
api_router.include_router(email_intake_route.router)

__all__ = ["api_router"]
