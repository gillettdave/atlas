"""Stable in-repo constants shared across migrations and runtime."""
from __future__ import annotations

import uuid

# Deterministic UUID for the single seeded local tenant (migration + bootstrap).
SEEDED_LOCAL_USER_ID = uuid.uuid5(
    uuid.NAMESPACE_DNS, "project-atlas.seeded-local-user"
)
