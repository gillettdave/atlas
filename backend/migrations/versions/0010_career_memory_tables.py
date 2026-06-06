"""career_memory tables — personal SoT scoped by user_id.

Revision ID: 0010_career_memory_tables
Revises: 0009_users_and_profile_scope
Create Date: 2026-04-29

Jobr-era career memory ported to PostgreSQL. Bigint IDs locally; canonical
Atlas job linkage via canonical_job_id (UUID) FK to jobs.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_career_memory_tables"
down_revision: Union[str, None] = "0009_users_and_profile_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "career_documents",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_career_documents_user_id", "career_documents", ["user_id"])

    op.create_table(
        "career_evidence_chunks",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("career_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_career_evidence_chunks_doc",
        "career_evidence_chunks",
        ["source_document_id"],
    )

    op.create_table(
        "career_facts",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("career_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("fact_text", sa.Text(), nullable=False),
        sa.Column("fact_type", sa.String(length=100), nullable=False, server_default="general"),
        sa.Column(
            "verification_state", sa.String(length=30), nullable=False, server_default="draft"
        ),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.6"),
        sa.Column("source_trace", sa.Text(), nullable=True),
        sa.Column("is_core_proof_point", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_career_facts_user_id", "career_facts", ["user_id"])

    op.create_table(
        "career_timeline_entries",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey("career_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("start_date", sa.String(length=20), nullable=True),
        sa.Column("end_date", sa.String(length=20), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.6"),
        sa.Column("conflict_group", sa.String(length=80), nullable=True),
        sa.Column("source_trace", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_career_timeline_entries_user", "career_timeline_entries", ["user_id"]
    )
    op.create_index(
        "ix_career_timeline_entries_doc",
        "career_timeline_entries",
        ["source_document_id"],
    )

    op.create_table(
        "career_discovery_profiles",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_name", sa.String(length=100), nullable=False, server_default="default"
        ),
        sa.Column("role_keywords_csv", sa.Text(), nullable=True),
        sa.Column("adjacency_keywords_csv", sa.Text(), nullable=True),
        sa.Column("seniority_keywords_csv", sa.Text(), nullable=True),
        sa.Column("avoid_keywords_csv", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.6"),
        sa.Column(
            "generated_from_facts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "profile_name",
            name="uq_career_discovery_profiles_user_profile",
        ),
    )

    op.create_table(
        "career_profile_questions",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "canonical_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "question_type", sa.String(length=50), nullable=False, server_default="gap"
        ),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
        sa.Column(
            "priority", sa.String(length=20), nullable=False, server_default="medium"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_career_profile_questions_user", "career_profile_questions", ["user_id"]
    )
    op.create_index(
        "ix_career_profile_questions_job",
        "career_profile_questions",
        ["canonical_job_id"],
    )

    op.create_table(
        "career_profile_answers",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column(
            "question_id",
            sa.BigInteger(),
            sa.ForeignKey("career_profile_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_career_profile_answers_question",
        "career_profile_answers",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_table("career_profile_answers")
    op.drop_table("career_profile_questions")
    op.drop_table("career_discovery_profiles")
    op.drop_table("career_timeline_entries")
    op.drop_table("career_facts")
    op.drop_table("career_evidence_chunks")
    op.drop_table("career_documents")
