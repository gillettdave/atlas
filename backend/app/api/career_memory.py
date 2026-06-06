"""Career memory API — `/career-memory` (Phase B slice)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select

from ..models.career_memory import (
    CareerDiscoveryProfile,
    CareerDocument,
    CareerFact,
    CareerProfileAnswer,
    CareerProfileQuestion,
    CareerTimelineEntry,
)
from ..models.job import Job
from ..schemas.career_memory import (
    CareerFactResponse,
    CareerFactUpdateRequest,
    CareerMemoryExportResponse,
    DiscoveryProfileResponse,
    ProfileAnswerCreateRequest,
    ProfileQuestionResponse,
    ProfileQuestionStatusUpdateRequest,
    SourceDocumentDetailResponse,
    SourceDocumentResponse,
    SourceDocumentTextIngestRequest,
    TimelineEntryResponse,
    TimelineEntryUpdateRequest,
)
from ..services.career_memory import (
    cleanup_unreadable_draft_facts,
    generate_profile_questions,
    get_discovery_profile_payload,
    ingest_source_document,
    prepare_upload_bytes_as_text,
    reextract_facts_for_document,
)

from ..config import Settings

from .deps import DbSession, SettingsDep, TenantUserId

router = APIRouter(prefix="/career-memory", tags=["career-memory"])


def _resolve_use_llm_facts(flag: bool | None, settings: Settings) -> bool:
    """True = LLM path, False = heuristic only, None = use settings default."""
    if flag is True:
        return True
    if flag is False:
        return False
    return bool(settings.career_memory_llm_facts_default)


def _iso_utc(dt) -> str | None:
    return dt.isoformat() if dt else None


def _preview_prefix(raw: str, preview_chars: int) -> str | None:
    if preview_chars <= 0:
        return None
    if not raw:
        return None
    if len(raw) > preview_chars:
        return raw[:preview_chars] + "…"
    return raw


def document_to_list_item(doc: CareerDocument, *, preview_chars: int) -> SourceDocumentResponse:
    return SourceDocumentResponse(
        id=doc.id,
        name=doc.name,
        content_type=doc.content_type,
        ingested_at=_iso_utc(doc.ingested_at),
        preview=_preview_prefix(doc.raw_text or "", preview_chars),
    )


def document_to_detail(doc: CareerDocument, *, max_chars: int | None) -> SourceDocumentDetailResponse:
    text = doc.raw_text or ""
    truncated = False
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return SourceDocumentDetailResponse(
        id=doc.id,
        name=doc.name,
        content_type=doc.content_type,
        ingested_at=_iso_utc(doc.ingested_at),
        raw_text=text,
        truncated=truncated,
    )


def _serialize_question(
    question: CareerProfileQuestion, jobs_by_id: dict[uuid.UUID, Job]
) -> ProfileQuestionResponse:
    job = (
        jobs_by_id.get(question.canonical_job_id) if question.canonical_job_id else None
    )
    return ProfileQuestionResponse(
        id=question.id,
        canonical_job_id=question.canonical_job_id,
        job_title=(job.title if job else None),
        job_company=(job.company_name if job else None),
        question_text=question.question_text,
        question_type=question.question_type,
        status=question.status,
        priority=question.priority,
    )


@router.post("/documents", response_model=SourceDocumentResponse)
async def upload_source_document(
    db: DbSession,
    tenant_id: TenantUserId,
    settings: SettingsDep,
    file: UploadFile = File(...),
    llm_facts: bool | None = Form(
        None,
        description="If true, extract facts via OpenAI. If false, heuristic lines only. "
        "Omit to use ATLAS_CAREER_MEMORY_LLM_FACTS_DEFAULT.",
    ),
) -> SourceDocumentResponse:
    data = await file.read()
    try:
        raw = prepare_upload_bytes_as_text(file.filename or "upload", file.content_type, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    use_llm = _resolve_use_llm_facts(llm_facts, settings)
    try:
        doc = ingest_source_document(
            db,
            file.filename or "upload",
            file.content_type,
            raw,
            user_id=tenant_id,
            use_llm_facts=use_llm,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return document_to_list_item(doc, preview_chars=500)


@router.post("/documents/text", response_model=SourceDocumentResponse)
def ingest_source_document_text(
    payload: SourceDocumentTextIngestRequest,
    db: DbSession,
    tenant_id: TenantUserId,
    settings: SettingsDep,
) -> SourceDocumentResponse:
    name = (payload.name or "manual_text").strip()[:255]
    text_value = (payload.text or "").strip()
    if not text_value:
        raise HTTPException(status_code=400, detail="text is required.")
    use_llm = _resolve_use_llm_facts(payload.llm_facts, settings)
    try:
        doc = ingest_source_document(
            db,
            name,
            "text/plain",
            text_value,
            user_id=tenant_id,
            use_llm_facts=use_llm,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return document_to_list_item(doc, preview_chars=500)


@router.get("/documents", response_model=list[SourceDocumentResponse])
def list_documents(
    db: DbSession,
    tenant_id: TenantUserId,
    preview_chars: int = Query(
        400,
        ge=0,
        le=10_000,
        description="Characters of raw_text to include in preview; 0 to omit.",
    ),
) -> list[SourceDocumentResponse]:
    rows = list(
        db.scalars(
            select(CareerDocument).where(CareerDocument.user_id == tenant_id).order_by(CareerDocument.id.desc())
        ).all()
    )
    return [document_to_list_item(d, preview_chars=preview_chars) for d in rows]


@router.get("/documents/{document_id}", response_model=SourceDocumentDetailResponse)
def get_document(
    document_id: int,
    db: DbSession,
    tenant_id: TenantUserId,
    max_chars: int | None = Query(
        None,
        ge=1,
        le=2_000_000,
        description="If set, truncate raw_text to this length. Omit for full text.",
    ),
) -> SourceDocumentDetailResponse:
    doc = db.get(CareerDocument, document_id)
    if not doc or doc.user_id != tenant_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document_to_detail(doc, max_chars=max_chars)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: int,
    db: DbSession,
    tenant_id: TenantUserId,
) -> None:
    doc = db.get(CareerDocument, document_id)
    if not doc or doc.user_id != tenant_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    from ..models.career_memory import CareerFact as CareerFactModel, CareerTimelineEntry
    # Delete only unreviewed facts — approved facts survive with source_document_id nulled
    # (the FK is ondelete="SET NULL" so the DB handles the null when the doc row is deleted).
    db.query(CareerFactModel).filter(
        CareerFactModel.source_document_id == document_id,
        CareerFactModel.user_id == tenant_id,
        CareerFactModel.verification_state.in_(["draft", "rejected"]),
    ).delete(synchronize_session=False)
    db.query(CareerTimelineEntry).filter(
        CareerTimelineEntry.source_document_id == document_id,
        CareerTimelineEntry.user_id == tenant_id,
    ).delete(synchronize_session=False)
    db.delete(doc)
    db.commit()


@router.post("/documents/{document_id}/re-extract", response_model=dict)
def re_extract_document_facts(
    document_id: int,
    db: DbSession,
    tenant_id: TenantUserId,
    settings: SettingsDep,
) -> dict:
    """Delete draft facts for a document and re-run LLM extraction.

    Approved and rejected facts are preserved. Returns the count of new facts created.
    """
    try:
        count = reextract_facts_for_document(db, document_id, tenant_id, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "new_facts": count}


@router.get("/facts", response_model=list[CareerFactResponse])
def list_facts(db: DbSession, tenant_id: TenantUserId) -> list[CareerFact]:
    return list(
        db.scalars(select(CareerFact).where(CareerFact.user_id == tenant_id).order_by(CareerFact.id.desc())).all()
    )


@router.get("/timeline", response_model=list[TimelineEntryResponse])
def list_timeline(db: DbSession, tenant_id: TenantUserId) -> list[TimelineEntryResponse]:
    rows = list(
        db.scalars(
            select(CareerTimelineEntry).where(CareerTimelineEntry.user_id == tenant_id).order_by(
                CareerTimelineEntry.id.desc()
            )
        ).all()
    )
    out: list[TimelineEntryResponse] = []
    for row in rows:
        created = row.created_at.isoformat() if row.created_at else None
        out.append(
            TimelineEntryResponse(
                id=row.id,
                source_document_id=row.source_document_id,
                title=row.title,
                company=row.company,
                start_date=row.start_date,
                end_date=row.end_date,
                summary=row.summary,
                status=row.status,
                confidence_score=row.confidence_score,
                conflict_group=row.conflict_group,
                source_trace=row.source_trace,
                created_at=created,
            )
        )
    return out


@router.patch("/timeline/{entry_id}", response_model=TimelineEntryResponse)
def update_timeline_entry(
    entry_id: int,
    payload: TimelineEntryUpdateRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> TimelineEntryResponse:
    entry = db.get(CareerTimelineEntry, entry_id)
    if not entry or entry.user_id != tenant_id:
        raise HTTPException(status_code=404, detail="Timeline entry not found.")
    for field in ("title", "company", "start_date", "end_date", "summary", "status"):
        value = getattr(payload, field)
        if value is not None:
            setattr(entry, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(entry)
    return TimelineEntryResponse(
        id=entry.id,
        source_document_id=entry.source_document_id,
        title=entry.title,
        company=entry.company,
        start_date=entry.start_date,
        end_date=entry.end_date,
        summary=entry.summary,
        status=entry.status,
        confidence_score=entry.confidence_score,
        conflict_group=entry.conflict_group,
        source_trace=entry.source_trace,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
    )


@router.get("/summary")
def career_memory_summary(db: DbSession, tenant_id: TenantUserId) -> dict:
    facts = list(db.scalars(select(CareerFact).where(CareerFact.user_id == tenant_id)).all())
    questions = list(
        db.scalars(select(CareerProfileQuestion).where(CareerProfileQuestion.user_id == tenant_id)).all()
    )
    by_type: dict[str, int] = {}
    for fact in facts:
        by_type[fact.fact_type] = by_type.get(fact.fact_type, 0) + 1
    underused_types = [k for k, v in sorted(by_type.items(), key=lambda item: item[1]) if v <= 2]
    return {
        "facts_total": len(facts),
        "facts_draft": sum(1 for f in facts if f.verification_state == "draft"),
        "facts_approved": sum(1 for f in facts if f.verification_state == "approved"),
        "facts_rejected": sum(1 for f in facts if f.verification_state == "rejected"),
        "core_proof_points": sum(1 for f in facts if f.is_core_proof_point == 1),
        "questions_open": sum(1 for q in questions if q.status == "open"),
        "questions_answered": sum(1 for q in questions if q.status == "answered"),
        "questions_dismissed": sum(1 for q in questions if q.status == "dismissed"),
        "underused_fact_types": underused_types[:5],
    }


@router.patch("/facts/{fact_id}", response_model=CareerFactResponse)
def update_fact(
    fact_id: int,
    payload: CareerFactUpdateRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> CareerFact:
    fact = db.get(CareerFact, fact_id)
    if not fact or fact.user_id != tenant_id:
        raise HTTPException(status_code=404, detail="Fact not found.")
    if payload.fact_text is not None:
        from datetime import datetime, timezone
        new_text = payload.fact_text.strip()
        if new_text != fact.fact_text:
            fact.fact_text = new_text
            fact.text_edited_at = datetime.now(timezone.utc)
    if payload.verification_state is not None:
        fact.verification_state = payload.verification_state
    if payload.is_core_proof_point is not None:
        fact.is_core_proof_point = payload.is_core_proof_point
    db.commit()
    db.refresh(fact)
    return fact


@router.delete("/facts/{fact_id}")
def delete_fact(
    fact_id: int,
    db: DbSession,
    tenant_id: TenantUserId,
) -> dict:
    """Permanently remove a fact row (manual cleanup; not soft-delete)."""
    fact = db.get(CareerFact, fact_id)
    if not fact or fact.user_id != tenant_id:
        raise HTTPException(status_code=404, detail="Fact not found.")
    db.delete(fact)
    db.commit()
    return {"ok": True, "deleted_id": fact_id}


@router.post("/questions/generate", response_model=list[ProfileQuestionResponse])
def create_profile_questions(
    db: DbSession,
    tenant_id: TenantUserId,
    canonical_job_id: uuid.UUID | None = None,
) -> list[ProfileQuestionResponse]:
    questions = generate_profile_questions(
        db, user_id=tenant_id, canonical_job_id=canonical_job_id
    )
    uniq = {q.canonical_job_id for q in questions if q.canonical_job_id is not None}
    jobs = list(db.scalars(select(Job).where(Job.id.in_(uniq))).all()) if uniq else []
    jobs_by_id = {job.id: job for job in jobs}
    return [_serialize_question(q, jobs_by_id) for q in questions]


@router.get("/questions", response_model=list[ProfileQuestionResponse])
def list_profile_questions(db: DbSession, tenant_id: TenantUserId) -> list[ProfileQuestionResponse]:
    questions = list(
        db.scalars(
            select(CareerProfileQuestion)
            .where(CareerProfileQuestion.user_id == tenant_id)
            .order_by(CareerProfileQuestion.id.desc())
        ).all()
    )
    job_ids_sub = [q.canonical_job_id for q in questions if q.canonical_job_id is not None]
    uniq_ids = {_ for _ in job_ids_sub if _ is not None}
    jobs = list(db.scalars(select(Job).where(Job.id.in_(uniq_ids))).all()) if uniq_ids else []
    jobs_by_id = {job.id: job for job in jobs}
    return [_serialize_question(q, jobs_by_id) for q in questions]


@router.post("/questions/{question_id}/answer")
def answer_profile_question(
    question_id: int,
    payload: ProfileAnswerCreateRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> dict:
    question = db.get(CareerProfileQuestion, question_id)
    if not question or question.user_id != tenant_id:
        raise HTTPException(status_code=404, detail="Question not found.")

    answer_text = payload.answer_text.strip()
    answer = CareerProfileAnswer(question_id=question.id, answer_text=answer_text)
    db.add(answer)
    question.status = "answered"

    fact_type = "profile_answer"
    verification_state = "approved" if len(answer_text.split()) >= 8 else "draft"
    confidence_score = 0.85 if verification_state == "approved" else 0.55
    trace = (
        f"question:{question.id}"
        + (f"|job:{question.canonical_job_id}" if question.canonical_job_id else "")
    )
    core_flag = (
        1
        if (question.priority == "high" and verification_state == "approved" and not question.canonical_job_id)
        else 0
    )
    created_fact = CareerFact(
        user_id=tenant_id,
        source_document_id=None,
        fact_text=answer_text,
        fact_type=fact_type,
        verification_state=verification_state,
        confidence_score=confidence_score,
        source_trace=trace,
        is_core_proof_point=core_flag,
    )
    db.add(created_fact)

    db.commit()
    return {
        "ok": True,
        "question_id": question.id,
        "created_fact_id": created_fact.id,
        "created_fact_state": verification_state,
        "is_core_proof_point": core_flag,
    }


@router.patch("/questions/{question_id}/status")
def update_question_status(
    question_id: int,
    payload: ProfileQuestionStatusUpdateRequest,
    db: DbSession,
    tenant_id: TenantUserId,
) -> dict:
    question = db.get(CareerProfileQuestion, question_id)
    if not question or question.user_id != tenant_id:
        raise HTTPException(status_code=404, detail="Question not found.")
    if payload.status not in {"open", "answered", "dismissed"}:
        raise HTTPException(status_code=400, detail="Invalid status.")
    question.status = payload.status
    db.commit()
    return {"ok": True, "question_id": question.id, "status": question.status}


@router.delete("/questions/{question_id}", status_code=204)
def delete_question(
    question_id: int,
    db: DbSession,
    tenant_id: TenantUserId,
) -> None:
    question = db.get(CareerProfileQuestion, question_id)
    if not question or question.user_id != tenant_id:
        raise HTTPException(status_code=404, detail="Question not found.")
    db.delete(question)
    db.commit()


@router.post("/facts/cleanup")
def cleanup_facts(db: DbSession, tenant_id: TenantUserId) -> dict:
    rejected = cleanup_unreadable_draft_facts(db, user_id=tenant_id)
    return {"ok": True, "rejected_count": rejected}


@router.get("/export/markdown", response_model=CareerMemoryExportResponse)
def export_career_memory_markdown(db: DbSession, tenant_id: TenantUserId) -> CareerMemoryExportResponse:
    timeline = list(
        db.scalars(
            select(CareerTimelineEntry).where(CareerTimelineEntry.user_id == tenant_id).order_by(
                CareerTimelineEntry.id.desc()
            )
        ).all()
    )
    facts = list(
        db.scalars(select(CareerFact).where(CareerFact.user_id == tenant_id).order_by(CareerFact.id.desc())).all())
    questions = list(
        db.scalars(
            select(CareerProfileQuestion)
            .where(CareerProfileQuestion.user_id == tenant_id)
            .order_by(CareerProfileQuestion.id.desc())
        ).all()
    )

    approved_timeline = [t for t in timeline if t.status == "approved"]
    approved_facts = [f for f in facts if f.verification_state == "approved"]

    lines: list[str] = []
    lines.append("# Personal Source of Truth (Structured)")
    lines.append("")
    lines.append("## Timeline (approved)")
    if not approved_timeline:
        lines.append("- (none yet)")
    for t in approved_timeline:
        date_span = f"{t.start_date or '?'} → {t.end_date or 'Present'}"
        header = f"- **{t.title}**" + (f" @ **{t.company}**" if t.company else "") + f" ({date_span})"
        lines.append(header)
        if t.summary:
            for ln in (t.summary or "").splitlines()[:8]:
                if ln.strip():
                    lines.append(f"  - {ln.strip()}")
    lines.append("")
    lines.append("## Facts (approved)")
    if not approved_facts:
        lines.append("- (none yet)")
    for f in approved_facts[:200]:
        lines.append(f"- {f.fact_text.strip()}")
    lines.append("")
    lines.append("## Open questions")
    open_q = [q for q in questions if q.status == "open"]
    if not open_q:
        lines.append("- (none)")
    for q in open_q[:200]:
        lines.append(f"- [{q.question_type}] {q.question_text.strip()}")

    return CareerMemoryExportResponse(markdown="\n".join(lines).strip() + "\n")


@router.get("/export/json")
def export_career_memory_json(db: DbSession, tenant_id: TenantUserId) -> dict:
    timeline = list(
        db.scalars(
            select(CareerTimelineEntry).where(CareerTimelineEntry.user_id == tenant_id).order_by(
                CareerTimelineEntry.id.desc()
            )
        ).all()
    )
    facts = list(
        db.scalars(select(CareerFact).where(CareerFact.user_id == tenant_id).order_by(CareerFact.id.desc())).all())
    questions = list(
        db.scalars(
            select(CareerProfileQuestion)
            .where(CareerProfileQuestion.user_id == tenant_id)
            .order_by(CareerProfileQuestion.id.desc())
        ).all()
    )
    documents = list(
        db.scalars(
            select(CareerDocument).where(CareerDocument.user_id == tenant_id).order_by(CareerDocument.id.desc())
        ).all()
    )
    return {
        "documents": [
            {
                "id": d.id,
                "name": d.name,
                "content_type": d.content_type,
                "ingested_at": d.ingested_at.isoformat() if d.ingested_at else None,
            }
            for d in documents
        ],
        "timeline": [
            {
                "id": t.id,
                "source_document_id": t.source_document_id,
                "title": t.title,
                "company": t.company,
                "start_date": t.start_date,
                "end_date": t.end_date,
                "summary": t.summary,
                "status": t.status,
                "confidence_score": t.confidence_score,
                "conflict_group": t.conflict_group,
                "source_trace": t.source_trace,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in timeline
        ],
        "facts": [
            {
                "id": f.id,
                "source_document_id": f.source_document_id,
                "fact_text": f.fact_text,
                "fact_type": f.fact_type,
                "verification_state": f.verification_state,
                "confidence_score": f.confidence_score,
                "source_trace": f.source_trace,
                "is_core_proof_point": f.is_core_proof_point,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in facts
        ],
        "questions": [
            {
                "id": q.id,
                "canonical_job_id": str(q.canonical_job_id) if q.canonical_job_id else None,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "status": q.status,
                "priority": q.priority,
                "created_at": q.created_at.isoformat() if q.created_at else None,
            }
            for q in questions
        ],
    }


@router.get("/discovery-profile", response_model=DiscoveryProfileResponse)
def get_discovery_profile(
    db: DbSession,
    tenant_id: TenantUserId,
    refresh: bool = False,
) -> DiscoveryProfileResponse:
    return DiscoveryProfileResponse(
        **get_discovery_profile_payload(db, user_id=tenant_id, refresh=refresh)
    )
