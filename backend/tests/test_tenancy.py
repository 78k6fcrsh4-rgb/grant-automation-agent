"""Does the scoping actually hold — especially across a reused connection."""
import sys
sys.path.insert(0, "/tmp/tenancy")

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.tenancy import (NoTenantScope, assert_not_privileged, install,
                         tenant_scope, unscoped)

APP_URL   = "postgresql+psycopg://gma_app@localhost:5433/gma_dupage"
ADMIN_URL = "postgresql+psycopg://gpadmin@localhost:5433/gma_dupage"
DUPAGE  = "aaaaaaaa-0000-0000-0000-000000000001"
DEBORAH = "bbbbbbbb-0000-0000-0000-000000000002"


@pytest.fixture(scope="module")
def engine():
    # pool_size=1, max_overflow=0: every session in this module is handed the
    # SAME physical connection, which is the arrangement a leak needs.
    eng = create_engine(APP_URL, pool_size=1, max_overflow=0, future=True)
    install(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def Session(engine):
    return sessionmaker(bind=engine, future=True)


def titles(session):
    return sorted(r[0] for r in session.execute(text("SELECT title FROM core.grants")))


def test_a_scoped_session_sees_only_its_own_organization(Session):
    with tenant_scope(DUPAGE):
        with Session() as s:
            assert titles(s) == ["DuPage grant"]
    with tenant_scope(DEBORAH):
        with Session() as s:
            assert titles(s) == ["Deborah grant"]


def test_an_unscoped_session_raises_rather_than_returning_nothing(Session):
    with pytest.raises(NoTenantScope):
        with Session() as s:
            s.execute(text("SELECT 1 FROM core.grants"))


def test_unscoped_permits_the_session_but_grants_no_visibility(Session):
    with unscoped("test: authenticating before the organization is known"):
        with Session() as s:
            assert titles(s) == []


def test_the_setting_is_transaction_local_on_its_own(engine):
    """The primary guarantee, tested with the safety net removed.

    The obvious version of this test closes the session, which returns the
    connection to the pool and fires the checkin reset — so it passes even
    when set_config is called with is_local=false and the setting is really
    session-lived. Verified: flipping that boolean left all eight tests
    green. The belt-and-braces was hiding the failure of the thing it is
    supposed to be backing up.

    So this holds ONE connection checked out, commits the scoped
    transaction, and looks at the setting before any cleanup can run. If
    SET LOCAL is not doing the work, the tenant is still there.
    """
    from sqlalchemy.orm import sessionmaker as _sm
    with engine.connect() as conn:
        with tenant_scope(DEBORAH):
            with _sm(bind=conn, future=True)() as s:
                assert titles(s) == ["Deborah grant"]
                s.commit()
        leftover = conn.exec_driver_sql(
            "SELECT current_setting('app.tenant_id', true)").scalar()
    assert leftover in (None, ""), (
        f"app.tenant_id survived the transaction as {leftover!r}. It is "
        f"session-lived, not transaction-lived — check that set_config's "
        f"third argument is true. The next request on this connection would "
        f"be scoped to the previous one's organization."
    )


def test_a_reused_connection_carries_nothing_between_organizations(Session, engine):
    """The leak this module exists to prevent, on one physical connection."""
    before = engine.pool.checkedin()
    with tenant_scope(DEBORAH):
        with Session() as s:
            assert titles(s) == ["Deborah grant"]
    # Same connection, different organization, immediately afterwards.
    with tenant_scope(DUPAGE):
        with Session() as s:
            seen = titles(s)
    assert seen == ["DuPage grant"], f"leaked across a reused connection: {seen}"
    assert engine.pool.size() == 1, "the pool was supposed to hold one connection"
    assert before >= 0


def test_repeated_alternation_never_leaks(Session):
    """Twenty alternations — a leak that needs a particular ordering shows up."""
    for i in range(20):
        tenant, expected = ((DUPAGE, "DuPage grant") if i % 2 == 0
                            else (DEBORAH, "Deborah grant"))
        with tenant_scope(tenant):
            with Session() as s:
                assert titles(s) == [expected], f"iteration {i}"


def test_refuses_to_run_as_a_privileged_role():
    admin = create_engine(ADMIN_URL, future=True)
    try:
        with pytest.raises(RuntimeError, match="Refusing to start"):
            assert_not_privileged(admin)
    finally:
        admin.dispose()


def test_accepts_the_application_role(engine):
    assert_not_privileged(engine)      # must not raise
