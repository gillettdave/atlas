"""E1+: unified `/applications/jobs/intake`."""


def test_synthesize_pasted_manual_payload() -> None:
    from app.services.manual_job_url import synthesize_pasted_manual_payload

    p = synthesize_pasted_manual_payload(
        "Staff Engineer — Platform Team\nExample Corp Remote\n\nBuild infra."
    )
    assert p["company_name"].lower() != ""
    assert p["job_title"].lower().startswith("staff")
    assert p["apply_url"].startswith("https://atlas.manual/")
    assert p["job_url"] == p["apply_url"]


def test_application_job_intake_router_prefix() -> None:
    from app.api.application_job_intake import router

    assert router.prefix == "/applications"
