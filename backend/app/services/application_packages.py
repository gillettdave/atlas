"""Template application packages — career-memory evidence + atlas job/job_scores (Phase D)."""
from __future__ import annotations

import logging
import uuid
from typing import Literal, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models.application_package import ApplicationPackage
from ..models.career_memory import CareerFact
from ..models.job import Job
from ..models.job_score import JobScore

log = logging.getLogger("atlas.packages")

TONE_GUIDANCE = {
    "balanced": "Use clear, professional language with moderate detail.",
    "concise": "Keep language tight and direct with shorter bullets and sentences.",
    "executive": "Use strategic, leadership-forward language emphasizing ownership and outcomes.",
    "technical": "Use implementation-oriented language with concrete tools, systems, and methods.",
}


def _collect_evidence(db: Session, user_id: uuid.UUID, *, limit: int = 20) -> list[str]:
    rows = db.scalars(
        select(CareerFact.fact_text)
        .where(
            CareerFact.user_id == user_id,
            CareerFact.verification_state != "rejected",
        )
        .order_by(
            CareerFact.is_core_proof_point.desc(),
            CareerFact.verification_state.desc(),   # approved > draft
            CareerFact.confidence_score.desc(),
        )
        .limit(limit)
    ).all()
    return [text.strip() for text in rows if text and text.strip()]


def _collect_evidence_summary(db: Session, user_id: uuid.UUID, *, limit: int = 20) -> str:
    rows = db.scalars(
        select(CareerFact)
        .where(
            CareerFact.user_id == user_id,
            CareerFact.verification_state != "rejected",
        )
        .order_by(
            CareerFact.is_core_proof_point.desc(),
            CareerFact.verification_state.desc(),
            CareerFact.confidence_score.desc(),
        )
        .limit(limit)
    ).all()
    if not rows:
        return "No approved/core evidence available yet."
    lines = [f"- Fact #{row.id}: {(row.fact_text or '').strip()}" for row in rows if (row.fact_text or '').strip()]
    return "\n".join(lines)


def latest_job_score(db: Session, job_id: uuid.UUID) -> JobScore | None:
    return db.scalar(
        select(JobScore)
        .where(JobScore.job_id == job_id)
        .order_by(JobScore.created_at.desc())
        .limit(1)
    )


def _job_summary(job: Job) -> str:
    lines = [
        f"- Role: {job.title or 'Unknown role'}",
        f"- Company: {job.company_name or 'Unknown company'}",
        f"- Location: {job.location or 'Unknown location'}",
    ]
    dc = job.description_clean
    if dc:
        lines.append(f"- Posting excerpt: {(dc.strip())[:430].strip()}…" if len(dc) > 430 else f"- Posting: {dc.strip()}")
    return "\n".join(lines)


def _score_section(score: JobScore | None) -> str:
    if score is None:
        return "No ranker score yet — ingest or rescore jobs to populate fit."
    return (
        f"- Bucket: {score.bucket}\n"
        f"- Score: {score.score}\n"
        f"- Hidden gem: {'yes' if score.hidden_gem else 'no'}\n"
        f"- Rationale:\n{(score.rationale or 'n/a')}"
    )


def _angle_hint(score: JobScore | None) -> str:
    if score is None or not (score.rationale or "").strip():
        return "execution, growth, and cross-functional alignment"
    first = score.rationale.strip().split("\n")[0].strip()
    return (first[:280] + "…") if len(first) > 280 else first


def _rec_close(score: JobScore | None) -> str:
    if score is None or not score.rationale:
        return "the posting aligns with the direction you're targeting."
    rt = score.rationale.strip()
    return rt[-560:] if len(rt) > 560 else rt


def _format_emphasis(emphasis: Sequence[str]) -> str:
    cleaned = [item.strip() for item in emphasis if item and item.strip()]
    return ", ".join(cleaned) if cleaned else "general fit"


def _build_strategy_notes(
    job: Job,
    score: JobScore | None,
    evidence: list[str],
    tone: str,
    emphasis: list[str],
) -> str:
    evidence_lines = "\n".join(f"- {item}" for item in evidence[:6]) or "- Add approved career evidence to tighten targeting."
    emphasis_text = _format_emphasis(emphasis)
    return (
        f"# Strategy Notes - {job.title or 'Role'} at {job.company_name or 'Company'}\n\n"
        "## Role Snapshot\n"
        f"{_job_summary(job)}\n\n"
        "## Draft Controls\n"
        f"- Tone: {tone}\n"
        f"- Emphasis: {emphasis_text}\n"
        f"- Guidance: {TONE_GUIDANCE.get(tone, TONE_GUIDANCE['balanced'])}\n\n"
        "## Narrative Anchor\n"
        f"{_angle_hint(score)}\n\n"
        "## Likely Risks To Address Early\n"
        "- Any gaps between headline fit and deepest requirements in the posting.\n\n"
        "## Ranker Snapshot\n"
        f"{_score_section(score)}\n\n"
        "## Proof Points Available\n"
        f"{evidence_lines}\n\n"
        "## Interview Bridge\n"
        "- Open with measurable outcomes that map directly to responsibilities.\n"
        "- Tie each claim to documented evidence.\n"
    )


def _build_resume_markdown(
    job: Job,
    score: JobScore | None,
    evidence: list[str],
    tone: str,
    emphasis: list[str],
) -> str:
    bullets = "\n".join(f"- {item}" for item in evidence) or "- Add approved proof points from career memory."
    emphasis_text = _format_emphasis(emphasis)
    angle = _angle_hint(score)
    reqs = (job.description_clean or "").strip()
    reqs_block = reqs[:1200] if reqs else "Add JD text via ingestion."
    return (
        f"# Tailored Resume Draft - {job.title or 'Role'}\n\n"
        f"## Target Role\n{job.title or 'Unknown role'} at {job.company_name or 'Unknown company'}\n\n"
        "## Draft Controls\n"
        f"- Tone: {tone}\n"
        f"- Emphasis: {emphasis_text}\n\n"
        "## Professional Summary\n"
        f"Outcome-focused operator. Primary framing: {angle}.\n\n"
        "## Selected Impact Highlights\n"
        f"{bullets}\n\n"
        "## Alignment to Posting\n"
        f"{reqs_block}\n"
    )


def _build_cover_letter_markdown(
    job: Job,
    score: JobScore | None,
    evidence: list[str],
    tone: str,
    emphasis: list[str],
) -> str:
    top_evidence = evidence[:3]
    evidence_para = "\n".join(f"- {item}" for item in top_evidence) if top_evidence else "- Add 2-3 verified proof points from career memory."
    emphasis_text = _format_emphasis(emphasis)
    comp = job.company_name or "the team"
    return (
        f"# Tailored Cover Letter Draft - {job.title or 'Role'} at {job.company_name or 'Company'}\n\n"
        f"Dear Hiring Team at {comp},\n\n"
        f"I am excited to apply for the {job.title or 'role'}. "
        f"My strengths align well with {_angle_hint(score)}.\n\n"
        "Relevant highlights include:\n"
        f"{evidence_para}\n\n"
        f"I am emphasizing these themes in this draft: {emphasis_text}. "
        f"Tone objective: {TONE_GUIDANCE.get(tone, TONE_GUIDANCE['balanced'])}\n\n"
        f"I am particularly motivated because {_rec_close(score)}\n\n"
        "Thank you for your time and consideration.\n\n"
        "Sincerely,\n"
        "[Your Name]\n"
    )


def _generate_with_ai(
    job: Job,
    score: JobScore | None,
    evidence: list[str],
    tone: str,
    emphasis: list[str],
    *,
    candidate=None,
) -> tuple[str, str]:
    """Call OpenAI to generate resume and cover letter. Returns (resume_md, cover_md).
    Raises on failure so caller can fall back to template."""
    from ..config import get_settings
    import openai

    cfg = get_settings()
    if not cfg.openai_api_key:
        raise RuntimeError("ATLAS_OPENAI_API_KEY not set")

    client = openai.OpenAI(api_key=cfg.openai_api_key)

    # Build candidate contact block
    if candidate and any([candidate.full_name, candidate.email, candidate.phone,
                          candidate.location, candidate.linkedin_url, candidate.website_url]):
        contact_lines = []
        if candidate.full_name:   contact_lines.append(f"Name: {candidate.full_name}")
        if candidate.email:       contact_lines.append(f"Email: {candidate.email}")
        if candidate.phone:       contact_lines.append(f"Phone: {candidate.phone}")
        if candidate.location:    contact_lines.append(f"Location: {candidate.location}")
        if candidate.linkedin_url: contact_lines.append(f"LinkedIn: {candidate.linkedin_url}")
        if candidate.website_url:  contact_lines.append(f"Website: {candidate.website_url}")
        if candidate.headline:     contact_lines.append(f"Headline: {candidate.headline}")
        contact_block = "\n".join(contact_lines)
    else:
        contact_block = "Not provided — use [Your Name], [Your Email], etc. as placeholders."

    evidence_block = "\n".join(f"- {e}" for e in evidence) if evidence else "- No approved career evidence yet."
    jd = (job.description_clean or "").strip()
    jd_excerpt = (jd[:3000] + "\n[...truncated]") if len(jd) > 3000 else jd
    score_text = _score_section(score)
    angle = _angle_hint(score)
    emphasis_text = _format_emphasis(emphasis)
    tone_guide = TONE_GUIDANCE.get(tone, TONE_GUIDANCE["balanced"])

    system_prompt = (
        "You are an expert career coach and professional writer specializing in tailored job applications. "
        "Write compelling, specific, honest content — never fabricate facts or invent metrics the candidate hasn't provided. "
        "Use only the evidence and job description supplied. Output clean Markdown."
    )

    user_prompt = f"""Write a tailored resume and cover letter for this job application.

## Candidate Contact Information
{contact_block}

## Target Role
- Title: {job.title or "Unknown"}
- Company: {job.company_name or "Unknown"}
- Location: {job.location or "Not specified"}

## Job Description
{jd_excerpt or "No job description available."}

## Ranker Fit Assessment
{score_text}

## Candidate's Proven Evidence (approved career facts)
{evidence_block}

## Application Strategy
- Tone: {tone} — {tone_guide}
- Emphasis themes: {emphasis_text}
- Lead narrative angle: {angle}

---

Output exactly two sections using these exact H2 headers. Do not add any text before the first header.

## Resume

Write a complete, polished, ATS-friendly resume. Include ALL of these sections in order:

**Header** (candidate's full name, email, phone, location, LinkedIn — use the contact info above; omit any fields not provided)

**Professional Summary** (3–4 sentences tailored to this specific role and company)

**Key Achievements** (6–8 bullet points drawn from the candidate's evidence above — use specific outcomes and metrics where available; do not invent facts not in the evidence)

**Core Skills** (12–16 skills as a comma-separated inline list, pulled from the job description and candidate evidence)

**Professional Experience** (2–3 most relevant roles implied by the evidence — use the facts provided to reconstruct role titles, responsibilities, and accomplishments; note these are derived from the candidate's career facts)

**Education & Certifications** (include only if mentioned in the evidence; otherwise omit this section)

Make the resume substantive — at least 400 words of content.

## Cover Letter

Write a compelling 4-paragraph cover letter:
1. Opening: hook + specific interest in this role/company + strongest qualification headline (2–3 sentences)
2. Achievements paragraph: 2–3 concrete examples from the candidate's evidence that directly address job requirements
3. Cultural fit / motivation paragraph: why this company, what draws them to this specific role
4. Close: confident call to action

Sign off with: "Sincerely,\\n{candidate.full_name if candidate and candidate.full_name else '[Your Name]'}"

Make the cover letter substantive — at least 250 words.

Use only the evidence provided. Do not invent facts. Be specific, not generic."""

    log.info(
        "Generating AI package for job=%s (%s at %s), model=%s",
        job.id,
        job.title,
        job.company_name,
        cfg.openai_model,
    )

    resp = client.chat.completions.create(
        model=cfg.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    full_text = resp.choices[0].message.content or ""

    # Split on the two H2 headers
    import re
    resume_match = re.search(r"^##\s*Resume\s*$", full_text, re.MULTILINE | re.IGNORECASE)
    cover_match = re.search(r"^##\s*Cover Letter\s*$", full_text, re.MULTILINE | re.IGNORECASE)

    if resume_match and cover_match:
        resume_start = resume_match.end()
        resume_end = cover_match.start()
        cover_start = cover_match.end()
        resume_md = full_text[resume_start:resume_end].strip()
        cover_md = full_text[cover_start:].strip()
    else:
        # Fallback: put full text in resume if parsing fails
        log.warning("AI output missing expected headers — using full text as resume")
        resume_md = full_text.strip()
        cover_md = ""

    # Add headers back
    resume_md = f"# Tailored Resume — {job.title or 'Role'} at {job.company_name or 'Company'}\n\n{resume_md}"
    cover_md = f"# Cover Letter — {job.title or 'Role'} at {job.company_name or 'Company'}\n\n{cover_md}"

    return resume_md, cover_md


def _next_version(db: Session, job_id: uuid.UUID, *, user_id: uuid.UUID) -> int:
    m = db.scalar(
        select(func.coalesce(func.max(ApplicationPackage.version), 0)).where(
            ApplicationPackage.job_id == job_id,
            ApplicationPackage.user_id == user_id,
        )
    )
    return int(m or 0) + 1


def _get_candidate_profile(db: Session, user_id: uuid.UUID):
    from ..models.candidate_profile import CandidateProfile
    return db.query(CandidateProfile).filter_by(user_id=user_id).first()


def generate_application_package(
    db: Session,
    job: Job,
    *,
    user_id: uuid.UUID,
    tone: str = "balanced",
    emphasis: list[str] | None = None,
    generation_source: str | None = None,
) -> ApplicationPackage:
    score = latest_job_score(db, job.id)
    evidence = _collect_evidence(db, user_id)
    evidence_summary = _collect_evidence_summary(db, user_id)
    emphasis_list = emphasis or []
    tone_value = tone.strip().lower() if tone and tone.strip() else "balanced"
    if tone_value not in TONE_GUIDANCE:
        tone_value = "balanced"
    nv = _next_version(db, job.id, user_id=user_id)
    strategy_notes = _build_strategy_notes(job, score, evidence, tone_value, emphasis_list)

    # Try AI generation if enabled; fall back to template on any error
    from ..config import get_settings
    _cfg = get_settings()
    ai_used = False
    candidate = _get_candidate_profile(db, user_id)
    if _cfg.packages_ai_enabled and _cfg.openai_api_key:
        try:
            resume_markdown, cover_md = _generate_with_ai(job, score, evidence, tone_value, emphasis_list, candidate=candidate)
            ai_used = True
        except Exception as exc:
            log.warning("AI package generation failed (%s) — falling back to template", exc)
            resume_markdown = _build_resume_markdown(job, score, evidence, tone_value, emphasis_list)
            cover_md = _build_cover_letter_markdown(job, score, evidence, tone_value, emphasis_list)
    else:
        resume_markdown = _build_resume_markdown(job, score, evidence, tone_value, emphasis_list)
        cover_md = _build_cover_letter_markdown(job, score, evidence, tone_value, emphasis_list)

    effective_source = "ai" if ai_used else (generation_source or "template")
    pkg = ApplicationPackage(
        user_id=user_id,
        job_id=job.id,
        version=nv,
        strategy_notes=strategy_notes,
        resume_markdown=resume_markdown,
        cover_letter_markdown=cover_md,
        generation_tone=tone_value,
        generation_emphasis=",".join(emphasis_list) if emphasis_list else None,
        generation_source=(effective_source.strip()[:50] if effective_source else None),
        evidence_used_summary=evidence_summary,
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return pkg


def save_edited_version(
    db: Session,
    job_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    resume_markdown: str,
    cover_letter_markdown: str,
    strategy_notes: str,
    evidence_used_summary: str | None = None,
) -> ApplicationPackage:
    nv = _next_version(db, job_id, user_id=user_id)
    pkg = ApplicationPackage(
        user_id=user_id,
        job_id=job_id,
        version=nv,
        strategy_notes=strategy_notes,
        resume_markdown=resume_markdown,
        cover_letter_markdown=cover_letter_markdown,
        generation_tone=None,
        generation_emphasis=None,
        generation_source="edited",
        evidence_used_summary=evidence_used_summary,
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return pkg


def list_for_job(db: Session, job_id: uuid.UUID, *, user_id: uuid.UUID) -> list[ApplicationPackage]:
    stmt = (
        select(ApplicationPackage)
        .where(
            ApplicationPackage.job_id == job_id,
            ApplicationPackage.user_id == user_id,
        )
        .order_by(ApplicationPackage.version.desc())
    )
    return list(db.scalars(stmt).all())


def get_one(
    db: Session,
    job_id: uuid.UUID,
    package_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
) -> ApplicationPackage | None:
    return db.scalar(
        select(ApplicationPackage).where(
            ApplicationPackage.id == package_id,
            ApplicationPackage.job_id == job_id,
            ApplicationPackage.user_id == user_id,
        )
    )


def export_docx_zip_bytes(pkg: ApplicationPackage) -> tuple[bytes, str]:
    """ZIP containing resume/cover/strategy `.docx` built from markdown fields."""
    from .application_package_docx import zip_application_package_docx

    return zip_application_package_docx(pkg)


def export_docx_single_bytes(
    pkg: ApplicationPackage,
    part: Literal["resume", "cover_letter", "strategy"],
) -> tuple[bytes, str]:
    """Single ``.docx`` for one draft field."""
    from .application_package_docx import single_application_package_docx

    return single_application_package_docx(pkg, part)
