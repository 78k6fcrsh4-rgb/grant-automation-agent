"""Does the tenant scoping hold — especially across a reused connection.

Needs two connection strings, because the point is to exercise the rules as
the *application* role rather than as the admin that migrations run as:

    TEST_DATABASE_URL=postgresql+psycopg://<admin>@localhost:5432/gma_test
    TEST_APP_DATABASE_URL=postgresql+psycopg://gma_app:<pw>@localhost:5432/gma_test

Without the second one these skip. A run that skips them proves nothing
about isolation — the admin bypasses every policy.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.tenancy import (NoTenantScope, assert_not_privileged,
                         bind_session_to_tenant, install,
                         mark_session_unscoped, tenant_scope, unscoped)
from tests.conftest import TEST_DATABASE_URL, migrate_test_database, needs_db

TEST_APP_DATABASE_URL = os.getenv("TEST_APP_DATABASE_URL")

pytestmark = [
    needs_db,
    pytest.mark.skipif(
        not TEST_APP_DATABASE_URL,
        reason="TEST_APP_DATABASE_URL (the gma_app role) is not set; tenant "
               "isolation cannot be tested as the admin, which bypasses every "
               "policy"),
]

DUPAGE = "aaaaaaaa-0000-0000-0000-000000000001"
DEBORAH = "bbbbbbbb-0000-0000-0000-000000000002"


@pytest.fixture(scope="module")
def two_organizations():
    """Two tenants with overlapping data, created as the admin."""
    migrate_test_database(TEST_DATABASE_URL)
    admin = create_engine(TEST_DATABASE_URL, future=True)
    with admin.begin() as conn:
        for tid, name, slug in ((DUPAGE, "DuPage Health Coalition", "dupage"),
                                (DEBORAH, "Deborah's Place", "deborahs")):
            uid = str(uuid.uuid5(uuid.UUID(tid), "user"))
            gid = str(uuid.uuid5(uuid.UUID(tid), "grant"))
            conn.execute(text(
                "INSERT INTO core.tenants (id,name,slug) VALUES (:i,:n,:s)"),
                {"i": tid, "n": name, "s": slug})
            conn.execute(text(
                "INSERT INTO core.users (id,tenant_id,email,hashed_password,role)"
                " VALUES (:u,:t,:e,'x','admin')"),
                {"u": uid, "t": tid, "e": f"{slug}@example.test"})
            conn.execute(text(
                "INSERT INTO core.grants (id,tenant_id,funder_name_raw,title,"
                "status,confirmed_by,confirmed_at) VALUES"
                " (:g,:t,'Funder',:title,'active',:u,now())"),
                {"g": gid, "t": tid, "u": uid, "title": f"{name} grant"})
            # A provenance row, so a view over three protected tables has
            # something to return.
            # A human correction has to say who made it — provenance is the
            # point of the table — so edited_by and edited_at come too.
            conn.execute(text(
                "INSERT INTO core.grant_field_provenance (grant_id, field_name,"
                " machine_value, human_value, edited_by, edited_at)"
                " VALUES (:g, :f, '1', '2', :u, now())"),
                {"g": gid, "f": f"{slug}_amount", "u": uid})
    yield {DUPAGE: "DuPage Health Coalition grant",
           DEBORAH: "Deborah's Place grant"}
    admin.dispose()


@pytest.fixture(scope="module")
def engine(two_organizations):
    # pool_size=1, max_overflow=0: every session here is handed the SAME
    # physical connection, which is the arrangement a leak needs.
    eng = create_engine(TEST_APP_DATABASE_URL, pool_size=1, max_overflow=0,
                        future=True)
    install(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def Session(engine):
    return sessionmaker(bind=engine, future=True)


def titles(session):
    return sorted(r[0] for r in session.execute(text("SELECT title FROM core.grants")))


def test_a_scoped_session_sees_only_its_own_organization(Session, two_organizations):
    for tenant, expected in two_organizations.items():
        with tenant_scope(tenant):
            with Session() as s:
                assert titles(s) == [expected]


def test_an_unscoped_session_raises_rather_than_returning_nothing(Session):
    """Silence would be safe but indistinguishable from "no data yet"."""
    with pytest.raises(NoTenantScope):
        with Session() as s:
            s.execute(text("SELECT 1 FROM core.grants"))


def test_unscoped_permits_the_session_but_grants_no_visibility(Session):
    with unscoped("test: authenticating before the organization is known"):
        with Session() as s:
            assert titles(s) == []


def test_the_setting_is_transaction_local_on_its_own(engine, two_organizations):
    """The primary guarantee, tested with the safety net removed.

    The obvious version of this closes the session, which returns the
    connection to the pool and fires the checkin reset — so it passes even
    when set_config is called with is_local=false and the setting is really
    session-lived. That was verified the hard way: flipping that boolean
    left every other test in this file green. The belt-and-braces was
    hiding the failure of the thing it exists to back up.

    So this holds ONE connection checked out, commits the scoped
    transaction, and reads the setting before any cleanup can run.
    """
    with engine.connect() as conn:
        with tenant_scope(DEBORAH):
            with sessionmaker(bind=conn, future=True)() as s:
                assert titles(s) == [two_organizations[DEBORAH]]
                s.commit()
        leftover = conn.exec_driver_sql(
            "SELECT current_setting('app.tenant_id', true)").scalar()
    assert leftover in (None, ""), (
        f"app.tenant_id survived the transaction as {leftover!r}. It is "
        f"session-lived, not transaction-lived — check set_config's third "
        f"argument. The next request on this connection would be scoped to "
        f"the previous one's organization."
    )


def test_a_reused_connection_carries_nothing_between_organizations(
        Session, engine, two_organizations):
    """The leak this module exists to prevent, on one physical connection."""
    with tenant_scope(DEBORAH):
        with Session() as s:
            assert titles(s) == [two_organizations[DEBORAH]]
    with tenant_scope(DUPAGE):
        with Session() as s:
            seen = titles(s)
    assert seen == [two_organizations[DUPAGE]], \
        f"leaked across a reused connection: {seen}"
    assert engine.pool.size() == 1, "the pool was supposed to hold one connection"


def test_repeated_alternation_never_leaks(Session, two_organizations):
    """Twenty alternations, in case a leak needs a particular ordering."""
    order = [DUPAGE, DEBORAH] * 10
    for i, tenant in enumerate(order):
        with tenant_scope(tenant):
            with Session() as s:
                assert titles(s) == [two_organizations[tenant]], f"iteration {i}"


def test_refuses_to_run_as_a_privileged_role():
    """Pointing DATABASE_URL at the admin would make every policy moot."""
    admin = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with pytest.raises(RuntimeError, match="Refusing to start"):
            assert_not_privileged(admin)
    finally:
        admin.dispose()


def test_accepts_the_application_role(engine):
    assert_not_privileged(engine)      # must not raise


def test_a_view_is_scoped_like_the_tables_beneath_it(Session, two_organizations):
    """The structural check says security_invoker is set; this says it works.

    Before migration 0006 every view ran with the owner's privileges and
    returned both organizations' rows to a session scoped to one — with RLS
    enabled on all the underlying tables and the drift test passing. The
    option being present is not the same as the scoping holding, and only
    one of those two things is what anyone actually cares about.

    core.v_extraction_overrides joins grant_field_provenance, grants and
    users, all three protected, which is the shape most likely to go wrong.
    """
    with tenant_scope(DUPAGE):
        with Session() as s:
            fields = sorted(r[0] for r in s.execute(
                text("SELECT field_name FROM core.v_extraction_overrides")))
    assert fields == ["dupage_amount"], (
        f"the view returned {fields} to a session scoped to DuPage — a view "
        f"without security_invoker bypasses every policy beneath it"
    )

    with unscoped("test: a view must disclose nothing with no tenant set"):
        with Session() as s:
            leaked = s.execute(text(
                "SELECT count(*) FROM core.v_extraction_overrides")).scalar()
    assert leaked == 0, f"the view returned {leaked} rows with no tenant set"


# ------------------------------------------------- binding to the session

def test_binding_the_session_scopes_it(Session, two_organizations):
    """The path FastAPI uses: the tenant travels on the Session object."""
    with Session() as s:
        bind_session_to_tenant(s, DEBORAH)
        assert titles(s) == [two_organizations[DEBORAH]]


def test_the_session_binding_beats_a_stale_ambient_value(Session, two_organizations):
    """If the two ever disagree, the explicit one must win.

    A ContextVar left over from earlier work in the same worker thread is
    exactly the kind of thing that would otherwise scope a request to the
    wrong organization while everything looks correct.
    """
    with tenant_scope(DUPAGE):                 # ambient says one thing...
        with Session() as s:
            bind_session_to_tenant(s, DEBORAH)  # ...the session says another
            assert titles(s) == [two_organizations[DEBORAH]], \
                "the ambient value overrode the session's explicit binding"


def test_binding_after_the_first_query_is_refused(Session):
    """Retrospective scoping is not scoping — earlier statements already ran.

    The session has to be marked unscoped first, because otherwise the guard
    stops the transaction from beginning at all: an unscoped `SELECT 1` is
    refused before it reaches the database. That is stronger than this test
    needs and worth knowing.
    """
    with Session() as s:
        mark_session_unscoped(s, "test: begin a transaction before binding")
        s.execute(text("SELECT 1"))            # transaction begins here
        with pytest.raises(NoTenantScope):
            bind_session_to_tenant(s, DUPAGE)


def test_an_unmarked_session_still_raises(Session):
    with pytest.raises(NoTenantScope):
        with Session() as s:
            s.execute(text("SELECT count(*) FROM core.grants"))


def test_marking_a_session_unscoped_permits_it_but_shows_nothing(Session):
    with Session() as s:
        mark_session_unscoped(s, "test: reading the login directory")
        assert titles(s) == []
        directory = s.execute(
            text("SELECT count(*) FROM core.tenant_directory")).scalar()
    assert directory == 2, "the login directory must be readable unscoped"
