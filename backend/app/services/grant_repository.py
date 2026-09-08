"""Where a grant lives while it is being worked on, and whether it survives.

GMA runs in one of two modes, chosen by GMA_PERSISTENCE:

    ephemeral  Standalone. Grant data is held in memory, purged after an
               idle window and on restart. Nothing reaches a database.
               This is the historical behaviour and remains the default.

    linked     Connected to Perch. Everything above still applies to the
               working copy; on confirm, the whitelisted record is filed
               to core.grants for Perch to read.

The in-memory store is the read path in BOTH modes, so the API surface,
the TTL and the single-replica requirement are unchanged by the choice.

The mode is not an implementation detail: /health reports it and the
review page shows it, because nobody should be under a data-retention
contract they cannot see.
"""
from __future__ import annotations

import glob
import os
import time
from typing import Dict, Optional
from uuid import UUID

from app.models.schemas import GrantData

TEMP_DIR = "temp_files"
GRANT_TTL_SECONDS = int(os.getenv("GRANT_TTL_MINUTES", "120")) * 60

EPHEMERAL = "ephemeral"
LINKED = "linked"


def configured_mode() -> str:
    mode = os.getenv("GMA_PERSISTENCE", EPHEMERAL).strip().lower()
    return LINKED if mode == LINKED else EPHEMERAL


class InMemoryGrantRepository:
    """Forget-by-design working store. No database, in either mode."""

    mode = EPHEMERAL
    persists = False

    def __init__(self, temp_dir: str = TEMP_DIR) -> None:
        # Instance attribute rather than a module global: the working store
        # owns the scratch directory, and having a second TEMP_DIR alias
        # elsewhere is how it ends up wiping the wrong one.
        self.temp_dir = temp_dir
        self.data: Dict[str, GrantData] = {}
        self.generated_docs: Dict[str, Dict[str, str]] = {}
        self.tenant: Dict[str, UUID] = {}
        self.created_at: Dict[str, float] = {}
        # file_id -> core.grants.id, populated on confirm in linked mode.
        self.filed_as: Dict[str, UUID] = {}
        # The six scalars exactly as the extractor produced them, snapshotted
        # before any human touches them. This is what makes machine_value in
        # core.grant_field_provenance honest: once a reviewer corrects a
        # figure the working copy holds their value, and the extractor's
        # claim would otherwise be gone.
        self.machine_scalars: Dict[str, Dict[str, Optional[str]]] = {}
        # file_id -> {field: {"by": user_id, "at": epoch}}
        self.edits: Dict[str, Dict[str, dict]] = {}

    # ---- working store -------------------------------------------------

    def put(self, file_id: str, grant_data: GrantData, tenant_id: UUID) -> None:
        from app.services.grant_persistence import PERSISTED_SCALARS

        self.data[file_id] = grant_data
        self.tenant[file_id] = tenant_id
        self.machine_scalars.setdefault(file_id, {
            field: (None if getattr(grant_data, field, None) is None
                    else str(getattr(grant_data, field)))
            for field in PERSISTED_SCALARS
        })
        self.touch(file_id)

    def record_edit(self, file_id: str, field: str, user_id: UUID) -> None:
        self.edits.setdefault(file_id, {})[field] = {
            "by": user_id, "at": time.time()}

    def get(self, file_id: str) -> Optional[GrantData]:
        return self.data.get(file_id)

    def __contains__(self, file_id: str) -> bool:
        return file_id in self.data

    def touch(self, file_id: str) -> None:
        """Sliding expiration — an active session is never purged mid-use."""
        self.created_at[file_id] = time.time()

    def owner(self, file_id: str) -> Optional[UUID]:
        return self.tenant.get(file_id)

    def ids_for_tenant(self, tenant_id: UUID) -> list[str]:
        return [fid for fid, owner in self.tenant.items() if owner == tenant_id]

    # ---- forgetting ----------------------------------------------------

    def delete_generated_files(self, file_id: str) -> None:
        for path in (self.generated_docs.get(file_id) or {}).values():
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    def forget(self, file_id: str) -> None:
        """Erase every trace of one grant's working copy.

        In linked mode a confirmed record already exists in core and is
        NOT touched — deleting the working copy is closing the session,
        not retracting the award. Deleting a filed grant is a separate,
        audited action.
        """
        self.delete_generated_files(file_id)
        self.data.pop(file_id, None)
        self.generated_docs.pop(file_id, None)
        self.tenant.pop(file_id, None)
        self.created_at.pop(file_id, None)
        self.filed_as.pop(file_id, None)
        self.machine_scalars.pop(file_id, None)
        self.edits.pop(file_id, None)

    def purge_expired(self) -> int:
        now = time.time()
        expired = [fid for fid, ts in list(self.created_at.items())
                   if now - ts > GRANT_TTL_SECONDS]
        for fid in expired:
            self.forget(fid)
        return len(expired)

    def clear_temp_dir(self) -> int:
        """Wipe files orphaned by a restart — the index that referenced
        them is gone, so they are unreferenced PII."""
        removed = 0
        for path in glob.glob(os.path.join(self.temp_dir, "*")):
            if path.endswith(".gitkeep"):
                continue
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
        return removed

    # ---- filing --------------------------------------------------------

    def confirm(self, file_id: str, *, tenant_id: UUID, user_id: UUID,
                db=None) -> Optional[UUID]:
        """Standalone: confirmation is a session fact and nothing is filed."""
        return None


class LinkedGrantRepository(InMemoryGrantRepository):
    """Everything above, plus a write-through to core.grants on confirm."""

    mode = LINKED
    persists = True

    def confirm(self, file_id: str, *, tenant_id: UUID, user_id: UUID,
                db=None) -> Optional[UUID]:
        from app.services.grant_persistence import persist_grant

        grant_data = self.get(file_id)
        if grant_data is None or db is None:
            return None
        if file_id in self.filed_as:
            return self.filed_as[file_id]

        grant = persist_grant(
            db, grant_data, tenant_id=tenant_id, user_id=user_id,
            machine_values=self.machine_scalars.get(file_id),
            edits=self.edits.get(file_id),
        )
        db.commit()
        self.filed_as[file_id] = grant.id
        return grant.id


def build_repository(mode: Optional[str] = None) -> InMemoryGrantRepository:
    mode = mode or configured_mode()
    return LinkedGrantRepository() if mode == LINKED else InMemoryGrantRepository()


repository: InMemoryGrantRepository = build_repository()
