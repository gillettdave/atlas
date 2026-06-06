"""Qualification MVP — deterministic rules (no DB)."""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.schemas.qualification import QualificationRules
from app.services.qualification import job_passes, rules_from_dict


def _job(
    *,
    title: str = "Senior Python Engineer",
    company: str = "Acme",
    description: str = "We use Python",
    remote: str | None = "remote",
) -> MagicMock:
    j = MagicMock()
    j.title = title
    j.company_name = company
    j.description_clean = description
    j.remote_type = remote
    return j


def test_rules_empty_passes() -> None:
    j = _job()
    ok, reasons = job_passes(j, ranking_score=Decimal("50"), rules=QualificationRules())
    assert ok is True
    assert reasons == []


def test_min_ranking_score() -> None:
    r = QualificationRules(min_ranking_score=60.0)
    ok, reasons = job_passes(
        _job(), ranking_score=Decimal("59.9"), rules=r
    )
    assert ok is False
    assert "below_min_ranking_score" in reasons


def test_remote_type_filter() -> None:
    r = QualificationRules(remote_types_allowed=["remote"])
    ok, _ = job_passes(_job(remote="remote"), ranking_score=Decimal("50"), rules=r)
    assert ok is True
    ok2, reasons2 = job_passes(
        _job(remote="onsite"), ranking_score=Decimal("50"), rules=r
    )
    assert ok2 is False
    assert "remote_type_not_allowed" in reasons2


def test_must_contain_any() -> None:
    r = QualificationRules(title_or_description_must_contain_any=["rust"])
    ok, reasons = job_passes(
        _job(description="only python"), ranking_score=Decimal("50"), rules=r
    )
    assert ok is False
    assert "must_contain_any_unsatisfied" in reasons


def test_block_text() -> None:
    r = QualificationRules(block_if_text_contains_any=["contractor"])
    ok, reasons = job_passes(
        _job(description="We need a contractor"), ranking_score=Decimal("50"), rules=r
    )
    assert ok is False
    assert any(x.startswith("blocked_text:") for x in reasons)


def test_company_block() -> None:
    r = QualificationRules(company_name_block_substrings=["spam"])
    ok, reasons = job_passes(
        _job(company="SpamCo LLC"), ranking_score=Decimal("50"), rules=r
    )
    assert ok is False
    assert any(x.startswith("blocked_company:") for x in reasons)


def test_rules_from_dict_unknown_keys_dropped() -> None:
    r = rules_from_dict(
        {"min_ranking_score": 40.0, "future_flag": True}  # type: ignore[arg-type]
    )
    assert r.min_ranking_score == 40.0
    dumped = r.model_dump(exclude_none=True)
    assert "future_flag" not in dumped


def test_no_ranking_when_required() -> None:
    r = QualificationRules(min_ranking_score=1.0)
    ok, reasons = job_passes(_job(), ranking_score=None, rules=r)
    assert ok is False
    assert "no_ranking_score" in reasons


@patch("app.services.qualification.profiles_svc.get_effective", return_value=None)
@patch("app.services.qualification.get_settings_dict")
def test_filter_jobs_by_qualification_drops_failed(
    mock_settings: MagicMock,
    _mock_eff: MagicMock,
) -> None:
    from app.services import qualification as qsvc

    mock_settings.return_value = {
        "title_or_description_must_contain_any": ["python"],
    }
    db = MagicMock()

    def _mk(title: str) -> MagicMock:
        j = MagicMock()
        j.title = title
        j.company_name = "Co"
        j.description_clean = ""
        j.remote_type = None
        j.ranking_score = Decimal("70")
        return j

    good = _mk("Senior Python Engineer")
    bad = _mk("Rust developer")
    kept, dropped = qsvc.filter_jobs_by_qualification(
        db,
        user_id=uuid.UUID("00000000-0000-4000-8000-0000000000aa"),
        jobs=[good, bad],
        profile_slug=None,
    )
    assert dropped == 1
    assert kept == [good]


@patch("app.services.qualification.profiles_svc.get_effective", return_value=None)
def test_evaluate_returns_job_not_found_shape(_mock_eff: MagicMock) -> None:
    """Smoke: evaluate_job_ids labels missing FK rows."""
    from app.constants import SEEDED_LOCAL_USER_ID
    from app.services import qualification as qsvc

    db = MagicMock()
    db.get = MagicMock(return_value=None)
    jid = uuid.uuid4()
    out = qsvc.evaluate_job_ids(
        db,
        user_id=SEEDED_LOCAL_USER_ID,
        job_ids=[jid],
        rules=QualificationRules(),
        profile_slug=None,
    )
    assert len(out) == 1
    assert out[0].job_id == jid
    assert out[0].passed is False
    assert "job_not_found" in out[0].reasons_failed


@patch("app.services.qualification.get_settings_dict", return_value={})
@patch("app.services.qualification.profiles_svc.get_effective", return_value=None)
def test_qualification_pass_map_all_true_when_rules_empty(
    _mock_eff: MagicMock,
    _mock_gs: MagicMock,
) -> None:
    from app.constants import SEEDED_LOCAL_USER_ID
    from app.services import qualification as qsvc

    db = MagicMock()
    j = MagicMock()
    jid = uuid.uuid4()
    j.id = jid
    m = qsvc.qualification_pass_map(
        db,
        user_id=SEEDED_LOCAL_USER_ID,
        jobs=[j],
        profile_slug=None,
    )
    assert m[jid] is True


@patch("app.services.qualification.get_settings_dict", return_value={})
@patch("app.services.qualification.profiles_svc.get_effective", return_value=None)
def test_qualification_pass_map_all_true_when_rules_empty(
    _mock_eff: MagicMock,
    _mock_gs: MagicMock,
) -> None:
    from app.constants import SEEDED_LOCAL_USER_ID
    from app.services import qualification as qsvc

    db = MagicMock()
    j = MagicMock()
    jid = uuid.uuid4()
    j.id = jid
    m = qsvc.qualification_pass_map(
        db,
        user_id=SEEDED_LOCAL_USER_ID,
        jobs=[j],
        profile_slug=None,
    )
    assert m[jid] is True