"""Ranker v2 text signals — TF–IDF aggregate + cosine (no DB)."""

from __future__ import annotations

import math
import uuid
from types import SimpleNamespace

from app.services import ranker_text as rt
from app.services.ranker import (
    DEFAULT_COMPONENT_WEIGHTS,
    ProfileRuntime,
    _score_description_fit,
    build_runtime,
)


def test_aggregate_tfidf_prefers_shared_terms() -> None:
    ref = rt.aggregate_tfidf_reference(
        [
            "senior rust engineer for defi protocol",
            "rust smart contract developer solidity",
        ]
    )
    assert "rust" in ref
    assert ref["rust"] >= ref.get("engineer", 0)


def test_cosine_identical_direction() -> None:
    a = {"x": 1.0 / math.sqrt(2), "y": 1.0 / math.sqrt(2)}
    b = {"x": 1.0 / math.sqrt(2), "y": 1.0 / math.sqrt(2)}
    assert abs(rt.cosine_sparse(a, b) - 1.0) < 1e-6


def test_cosine_orthogonal() -> None:
    a = {"x": 1.0}
    b = {"y": 1.0}
    assert rt.cosine_sparse(a, b) == 0.0


def test_build_runtime_loads_ranker_text_signals() -> None:
    p = SimpleNamespace(
        slug="t1",
        id=uuid.uuid4(),
        is_default=False,
        weights={},
        strong_keywords=[],
        weak_keywords=[],
        negative_keywords=[],
        preferred_remote=None,
        ranker_text_signals={
            "ref_vector": {"rust": 0.8, "solidity": 0.6},
            "suggested_keywords": ["kubernetes"],
        },
    )
    r = build_runtime(p)  # type: ignore[arg-type]
    assert "rust" in r.description_ref_vector
    assert "kubernetes" in r.note_suggested_terms


def test_score_description_fit_bonus_for_overlap() -> None:
    job = SimpleNamespace(
        description_clean="we use rust and kubernetes for our stack",
        title="",
    )
    rt_obj = ProfileRuntime(
        slug="p",
        profile_id=uuid.uuid4(),
        weights=dict(DEFAULT_COMPONENT_WEIGHTS),
        preferred_remote=None,
        extra_strong_words=set(),
        extra_strong_phrases=set(),
        extra_weak_words=set(),
        extra_weak_phrases=set(),
        negative_words=set(),
        negative_phrases=set(),
        strong_word_re=None,
        weak_word_re=None,
        negative_word_re=None,
        is_default=False,
        description_ref_vector={},
        note_suggested_terms=frozenset({"kubernetes", "rust"}),
    )
    score, notes = _score_description_fit(job, rt_obj)  # type: ignore[arg-type]
    assert score > 0
    assert any("note-keyword" in n for n in notes)
