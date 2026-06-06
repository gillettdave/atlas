"""Phase E1: application-job track routes under `/applications/job-tracks`."""


def test_application_job_tracks_router_prefix() -> None:
    from app.api.application_job_tracks import router

    assert router.prefix == "/applications/job-tracks"


def test_duplicate_track_exception_is_defined() -> None:
    from app.services.application_job_tracks import DuplicateTrackError

    assert issubclass(DuplicateTrackError, Exception)
