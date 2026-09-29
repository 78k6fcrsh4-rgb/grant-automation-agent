"""Binding every database session to exactly one organization.

With every organization in one database, this module is the whole of the
isolation guarantee on the application side. Migration 0005 writes the
policies; this decides which tenant those policies compare against, and
refuses to run a query when the answer is unknown.

THE FAILURE THIS IS SHAPED AROUND

Connection pooling. A pooled connection that still carries the previous
request's app.tenant_id, handed to the next request, serves one nonprofit's
grant data to another — with a 200, no exception and no log line. Nobody
finds out until a board sees figures that are not theirs.

Three things prevent it, in order of how much they are relied on:

1. SET LOCAL, via set_config(..., true). Transaction-scoped: Postgres
   discards it at COMMIT or ROLLBACK, so it *cannot* outlive the
   transaction that set it, whatever the pool does afterwards. This is the
   guarantee; the other two are belt and braces.

2. A guard that raises. A session that begins with no tenant in context
   raises rather than proceeding. Without it an unscoped query would
   silently return nothing (the policies compare against NULL) — safe, but
   it turns a bug into an empty page that looks like missing data and gets
   diagnosed for hours.

3. A reset on pool checkin, for the case where a connection is returned
   outside a transaction.

set_config's third argument is what makes it local. Passing false there, or
using plain SET, makes the setting session-lived and the leak real. That one
boolean is the difference.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional, Union

from sqlalchemy import event, text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# The tenant the current request belongs to. A ContextVar rather than a
# module global because FastAPI serves requests concurrently on one thread
# via asyncio: a global would be shared between them, which is the same
# leak in a different costume.
_current_tenant: ContextVar[Optional[str]] = ContextVar("current_tenant", default=None)

# Set only inside unscoped(), which is deliberately awkward to reach.
_unscoped: ContextVar[bool] = ContextVar("unscoped", default=False)


class NoTenantScope(RuntimeError):
    """A database session began with no organization in context.

    Raised rather than allowed to proceed. The policies would have returned
    nothing, which is safe but indistinguishable from an organization that
    genuinely has no data — and that ambiguity costs hours.
    """


def current_tenant() -> Optional[str]:
    return _current_tenant.get()


def bind_session_to_tenant(session, tenant_id: Union[str, uuid.UUID]) -> None:
    """Scope one Session object to one organization.

    Preferred over the ContextVar inside FastAPI. Sync dependencies and sync
    endpoints run in threadpool workers, and a ContextVar set in one worker
    is not reliably visible in another — so ambient context is the wrong
    place to keep something that must never be wrong. The tenant travels on
    the Session instead, which is the object the queries actually use.

    Must be called before the session's first query: the scoping is applied
    when its transaction begins, and a transaction that has already begun
    cannot be retrospectively scoped.
    """
    value = str(tenant_id)
    uuid.UUID(value)                      # reject non-ids here, loudly
    if session.in_transaction():
        raise NoTenantScope(
            "bind_session_to_tenant() was called after the session had "
            "already begun a transaction, so earlier statements in it ran "
            "unscoped. Bind before the first query."
        )
    session.info["tenant_id"] = value


def mark_session_unscoped(session, reason: str) -> None:
    """Permit one Session to run with no organization. See unscoped()."""
    log.info("unscoped database session: %s", reason)
    session.info["unscoped"] = reason


@contextmanager
def tenant_scope(tenant_id: Union[str, uuid.UUID]) -> Iterator[str]:
    """Bind everything in this block to one organization."""
    if tenant_id in (None, ""):
        raise NoTenantScope("tenant_scope requires a tenant id")
    value = str(tenant_id)
    uuid.UUID(value)          # reject anything that is not an id, loudly, here
    token = _current_tenant.set(value)
    try:
        yield value
    finally:
        _current_tenant.reset(token)


@contextmanager
def unscoped(reason: str) -> Iterator[None]:
    """Permit sessions with no tenant, for the few paths that predate one.

    Every use is a hole in the isolation model and has to earn its place:
    authenticating a user before their organization is known, seeding the
    first tenant, the startup health check. It takes a reason because the
    reason is the thing a reviewer needs, and it logs at INFO so the set of
    unscoped paths is discoverable from a running system rather than only
    by grepping.

    It does NOT bypass the policies — an unscoped session still sees no
    tenant-scoped rows. It only permits the session to open.
    """
    log.info("unscoped database access: %s", reason)
    token = _unscoped.set(True)
    try:
        yield
    finally:
        _unscoped.reset(token)


def install(engine) -> None:
    """Attach the scoping listeners to an engine and its sessions."""

    @event.listens_for(Session, "after_begin")
    def _scope_transaction(session, transaction, connection):  # noqa: ANN001
        if connection.engine is not engine:
            return
        # The session's own binding wins. The ContextVar is the fallback,
        # for code that is not running under a FastAPI request.
        tenant = session.info.get("tenant_id") or _current_tenant.get()
        if tenant is None:
            if session.info.get("unscoped") or _unscoped.get():
                return
            raise NoTenantScope(
                "A database session began with no organization in context. "
                "Wrap the work in tenancy.tenant_scope(user.tenant_id), or — "
                "if this genuinely runs before any organization is known — in "
                "tenancy.unscoped('why')."
            )
        # set_config's third argument is `is_local`. True means the setting
        # dies with this transaction and cannot ride a pooled connection to
        # the next request.
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant}
        )

    @event.listens_for(engine, "checkin")
    def _clear_on_checkin(dbapi_connection, connection_record):  # noqa: ANN001
        """Belt and braces for connections returned outside a transaction.

        SET LOCAL already cannot survive a completed transaction. This
        covers the case where something set the GUC outside one.
        """
        try:
            with dbapi_connection.cursor() as cur:
                cur.execute("SELECT set_config('app.tenant_id', '', false)")
            dbapi_connection.commit()
        except Exception:  # noqa: BLE001
            # A connection being discarded because it is broken will fail
            # here; that is not worth an error, and the connection is going
            # away regardless.
            pass


def assert_not_privileged(engine) -> None:
    """Refuse to run as a role that row-level security does not apply to.

    Migration 0005 cannot use FORCE ROW LEVEL SECURITY — it would apply the
    policies to the owner, which is the admin Alembic runs as, and silently
    filter data migrations. This is the property FORCE would otherwise have
    provided, asserted where it can be tested: if the application is ever
    pointed at an admin connection string, every organization's data is
    readable regardless of policy, and it should refuse to start rather than
    serve.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT current_user AS who,
                   r.rolsuper   AS is_super,
                   r.rolbypassrls AS bypasses,
                   pg_catalog.pg_get_userbyid(c.relowner) = current_user AS owns_core
              FROM pg_roles r
              LEFT JOIN pg_class c ON c.oid = 'core.grants'::regclass
             WHERE r.rolname = current_user
        """)).one()

    problems = []
    if row.is_super:
        problems.append("it is a superuser")
    if row.bypasses:
        problems.append("it has BYPASSRLS")
    if row.owns_core:
        problems.append("it owns core.grants, and owners are not subject to "
                        "the policies")
    if problems:
        raise RuntimeError(
            f"Refusing to start: the database role '{row.who}' can read every "
            f"organization's data because " + ", and ".join(problems) + ". "
            "Point DATABASE_URL at the gma_app role. Admin credentials are "
            "for migrations."
        )
