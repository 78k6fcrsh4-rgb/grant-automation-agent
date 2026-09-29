"""An adversarial battery: every way one organization's data could reach another.

This exists because the isolation tests written alongside the implementation
kept passing while real leaks were live — views bypassing every policy, a
TRUNCATE grant that erases both organizations at once, a transaction-local
setting that was never actually transaction-local. Each was found by attacking
the system rather than by confirming it worked.

So this file is written from the attacker's side. Every check runs as the
APPLICATION role, never the admin, against a database holding two
organizations with deliberately overlapping data, and each one tries to get
at the other organization's rows by a different route.

It cannot prove leakage is impossible. It enumerates the channels that are
known to exist in Postgres row-level security and tries each:

    reads      every protected table, every readable view, aggregates,
               joins, CTEs, EXISTS probes, and the unscoped case
    writes     inserting as another tenant, updating and deleting another
               tenant's rows, moving a row between tenants, writing a child
               row onto another tenant's parent
    privilege  TRUNCATE and REFERENCES (which policies do not constrain),
               BYPASSRLS, role membership, SECURITY DEFINER functions,
               materialised views, owner-scoped views
    oracles    what an error message discloses about rows you cannot read

Requires both connection strings; skips without them, because running as the
admin proves nothing.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.tenancy import install, tenant_scope, unscoped
from tests.conftest import TEST_DATABASE_URL, migrate_test_database, needs_db

TEST_APP_DATABASE_URL = os.getenv("TEST_APP_DATABASE_URL")

pytestmark = [
    needs_db,
    pytest.mark.skipif(
        not TEST_APP_DATABASE_URL,
        reason="TEST_APP_DATABASE_URL (the gma_app role) is not set; leakage "
               "cannot be tested as the admin, which bypasses every policy"),
]

OURS   = "aaaaaaaa-0000-0000-0000-000000000001"   # the tenant we are scoped to
THEIRS = "bbbbbbbb-0000-0000-0000-000000000002"   # the tenant we must not reach

# Everything gma_app can read that is scoped to an organization. Each is
# probed separately: "no rows leaked overall" is a much weaker claim than
# "no rows leaked from this table".
GMA_READABLE = [
    ("core.tenants", "id"),
    ("core.users", "tenant_id"),
    ("core.grants", "tenant_id"),
    ("core.obligations", "tenant_id"),
    ("core.documents", "tenant_id"),
    ("core.funders", "tenant_id"),
    ("core.metric_definitions", "tenant_id"),
    ("core.audit_log", "tenant_id"),
]

# Child tables with no tenant_id, scoped through a parent by EXISTS.
GMA_CHILD_TABLES = [
    "core.grant_field_provenance",
    "core.grant_contacts",
    "core.grant_budget_lines",
    "core.grant_workplan_tasks",
    "core.obligation_criteria",
]


@pytest.fixture(scope="module")
def two_organizations():
    """Two organizations, overlapping in every way that could confuse a filter."""
    migrate_test_database(TEST_DATABASE_URL)
    admin = create_engine(TEST_DATABASE_URL, future=True)
    ids = {}
    with admin.begin() as c:
        for tid, name, slug in ((OURS, "Ours Coalition", "ours"),
                                (THEIRS, "Theirs Incorporated", "theirs")):
            uid = str(uuid.uuid5(uuid.UUID(tid), "user"))
            gid = str(uuid.uuid5(uuid.UUID(tid), "grant"))
            oid = str(uuid.uuid5(uuid.UUID(tid), "obligation"))
            did = str(uuid.uuid5(uuid.UUID(tid), "document"))
            ids[tid] = {"user": uid, "grant": gid, "obligation": oid, "doc": did}
            c.execute(text("INSERT INTO core.tenants (id,name,slug)"
                           " VALUES (:i,:n,:s)"),
                      {"i": tid, "n": name, "s": slug})
            c.execute(text("INSERT INTO core.users (id,tenant_id,email,"
                           "hashed_password,role) VALUES (:u,:t,:e,'hash','admin')"),
                      {"u": uid, "t": tid, "e": f"{slug}@example.test"})
            # Deliberately identical titles: a filter that works by name
            # rather than by tenant passes the naive test and fails here.
            c.execute(text("INSERT INTO core.grants (id,tenant_id,funder_name_raw,"
                           "title,status,confirmed_by,confirmed_at) VALUES"
                           " (:g,:t,'Shared Funder Name','Annual Operating Grant',"
                           "'active',:u,now())"),
                      {"g": gid, "t": tid, "u": uid})
            c.execute(text("INSERT INTO core.obligations (id,tenant_id,grant_id,"
                           "kind,title,due_date) VALUES"
                           " (:o,:t,:g,'report','Q1 report','2027-03-31')"),
                      {"o": oid, "t": tid, "g": gid})
            c.execute(text("INSERT INTO core.grant_field_provenance (grant_id,"
                           "field_name,machine_value,human_value,edited_by,"
                           "edited_at) VALUES (:g,:f,'1','2',:u,now())"),
                      {"g": gid, "f": f"{slug}_secret_amount", "u": uid})
            c.execute(text("INSERT INTO core.audit_log (tenant_id,actor_user_id,"
                           "action,entity_schema,entity_table,new_value)"
                           " VALUES (:t,:u,'test','core','grants',:v)"),
                      {"t": tid, "u": uid, "v": f"{slug}-audit-value"})
    yield ids
    admin.dispose()


@pytest.fixture(scope="module")
def engine(two_organizations):
    eng = create_engine(TEST_APP_DATABASE_URL, pool_size=1, max_overflow=0,
                        future=True)
    install(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def Session(engine):
    return sessionmaker(bind=engine, future=True)


@pytest.fixture
def admin_engine():
    eng = create_engine(TEST_DATABASE_URL, future=True)
    yield eng
    eng.dispose()


# ====================================================================== reads

@pytest.mark.parametrize("table,col", GMA_READABLE, ids=[t for t, _ in GMA_READABLE])
def test_no_row_of_the_other_organization_is_readable(Session, table, col):
    """Per table, not in aggregate. A single leaking table is the whole problem."""
    with tenant_scope(OURS):
        with Session() as s:
            theirs = s.execute(
                text(f"SELECT count(*) FROM {table} WHERE {col} = :t"),
                {"t": THEIRS}).scalar()
    assert theirs == 0, f"{table} returned {theirs} of the other organization's rows"


@pytest.mark.parametrize("table", GMA_CHILD_TABLES)
def test_child_tables_are_scoped_through_their_parent(Session, table, two_organizations):
    """No tenant_id of their own — the EXISTS policy is all that protects them."""
    theirs_grant = two_organizations[THEIRS]["grant"]
    theirs_oblig = two_organizations[THEIRS]["obligation"]
    fk = "obligation_id" if table.endswith("obligation_criteria") else "grant_id"
    target = theirs_oblig if fk == "obligation_id" else theirs_grant
    with tenant_scope(OURS):
        with Session() as s:
            leaked = s.execute(
                text(f"SELECT count(*) FROM {table} WHERE {fk} = :x"),
                {"x": target}).scalar()
    assert leaked == 0, f"{table} exposed {leaked} rows belonging to the other organization"


def test_totals_do_not_include_the_other_organization(Session):
    """An aggregate is a read too, and leaks a number rather than a row."""
    with tenant_scope(OURS):
        with Session() as s:
            n = s.execute(text("SELECT count(*) FROM core.grants")).scalar()
            names = s.execute(text("SELECT count(DISTINCT title) FROM core.grants")).scalar()
    assert n == 1, f"counted {n} grants; both organizations have one each"
    assert names == 1


def test_a_join_across_protected_tables_stays_scoped(Session):
    with tenant_scope(OURS):
        with Session() as s:
            rows = s.execute(text("""
                SELECT g.title, o.title, u.email
                  FROM core.grants g
                  JOIN core.obligations o ON o.grant_id = g.id
                  JOIN core.users u ON u.id = g.confirmed_by
            """)).all()
    assert len(rows) == 1, f"the join returned {len(rows)} rows across organizations"
    assert "theirs" not in rows[0][2]


def test_a_cte_does_not_smuggle_rows_past_the_policy(Session):
    with tenant_scope(OURS):
        with Session() as s:
            n = s.execute(text("""
                WITH everything AS (SELECT * FROM core.grants)
                SELECT count(*) FROM everything
            """)).scalar()
    assert n == 1


def test_an_exists_probe_cannot_confirm_their_rows(Session, two_organizations):
    """Asking "does this row exist" is a read, and must answer no."""
    theirs = two_organizations[THEIRS]["grant"]
    with tenant_scope(OURS):
        with Session() as s:
            found = s.execute(
                text("SELECT EXISTS (SELECT 1 FROM core.grants WHERE id = :g)"),
                {"g": theirs}).scalar()
    assert found is False, "an EXISTS probe confirmed a row the policy hides"


def test_a_view_over_protected_tables_stays_scoped(Session):
    with tenant_scope(OURS):
        with Session() as s:
            fields = [r[0] for r in s.execute(
                text("SELECT field_name FROM core.v_extraction_overrides"))]
    assert all("theirs" not in f for f in fields), \
        f"the view disclosed the other organization's rows: {fields}"


def test_nothing_is_readable_with_no_tenant_set(Session):
    with unscoped("test: the unscoped case must disclose nothing"):
        with Session() as s:
            for table, _ in GMA_READABLE:
                n = s.execute(text(f"SELECT count(*) FROM {table}")).scalar()
                assert n == 0, f"{table} returned {n} rows with no tenant set"


def test_the_directory_discloses_only_names_and_ids(Session):
    """It is globally readable on purpose; that purpose has to stay narrow."""
    with unscoped("test: the login directory is read before a tenant is known"):
        with Session() as s:
            cols = [r[0] for r in s.execute(text("""
                SELECT column_name FROM information_schema.columns
                 WHERE table_schema='core' AND table_name='tenant_directory'
            """))]
            rows = s.execute(text("SELECT count(*) FROM core.tenant_directory")).scalar()
    assert sorted(cols) == ["id", "slug"], \
        f"the login directory exposes more than slug and id: {cols}"
    assert rows == 2, "the directory should list every organization — that is its job"


# ===================================================================== writes

def test_cannot_insert_a_row_belonging_to_the_other_organization(Session, two_organizations):
    from sqlalchemy.exc import ProgrammingError, IntegrityError
    with tenant_scope(OURS):
        with Session() as s:
            with pytest.raises((ProgrammingError, IntegrityError)):
                s.execute(text("""
                    INSERT INTO core.obligations (tenant_id,grant_id,kind,title,due_date)
                    VALUES (:t,:g,'report','planted','2027-01-01')
                """), {"t": THEIRS, "g": two_organizations[THEIRS]["grant"]})
                s.commit()


def test_cannot_update_the_other_organizations_rows(Session, admin_engine):
    with tenant_scope(OURS):
        with Session() as s:
            s.execute(text("UPDATE core.grants SET title = 'hijacked'"))
            s.commit()
    with admin_engine.connect() as c:
        theirs = c.execute(text("SELECT title FROM core.grants WHERE tenant_id = :t"),
                           {"t": THEIRS}).scalar()
    assert theirs != "hijacked", "an unqualified UPDATE reached the other organization"


def test_cannot_move_our_row_into_their_organization(Session, admin_engine):
    """WITH CHECK, not just USING: rewriting tenant_id must be refused."""
    from sqlalchemy.exc import ProgrammingError, IntegrityError
    with tenant_scope(OURS):
        with Session() as s:
            with pytest.raises((ProgrammingError, IntegrityError)):
                s.execute(text("UPDATE core.grants SET tenant_id = :t"), {"t": THEIRS})
                s.commit()


def test_cannot_attach_a_child_row_to_their_parent(Session, two_organizations):
    """The EXISTS policy has to constrain writes as well as reads."""
    from sqlalchemy.exc import ProgrammingError, IntegrityError
    with tenant_scope(OURS):
        with Session() as s:
            with pytest.raises((ProgrammingError, IntegrityError)):
                s.execute(text("""
                    INSERT INTO core.grant_field_provenance
                        (grant_id, field_name, machine_value)
                    VALUES (:g, 'planted', 'x')
                """), {"g": two_organizations[THEIRS]["grant"]})
                s.commit()


def test_an_unqualified_delete_cannot_reach_them(Session, admin_engine):
    """DELETE is policy-constrained; this proves it rather than assuming."""
    from sqlalchemy.exc import ProgrammingError
    with admin_engine.connect() as c:
        before = c.execute(text("SELECT count(*) FROM core.audit_log WHERE tenant_id = :t"),
                           {"t": THEIRS}).scalar()
    with tenant_scope(OURS):
        with Session() as s:
            try:
                s.execute(text("DELETE FROM core.audit_log"))
                s.commit()
            except ProgrammingError:
                pass          # no DELETE privilege is an even better answer
    with admin_engine.connect() as c:
        after = c.execute(text("SELECT count(*) FROM core.audit_log WHERE tenant_id = :t"),
                          {"t": THEIRS}).scalar()
    assert after == before, \
        f"the other organization's audit rows went from {before} to {after}"


# ================================================================= privileges

def test_app_roles_hold_no_privilege_that_policies_cannot_constrain(admin_engine):
    """TRUNCATE ignores row-level security entirely.

    This is not hypothetical. GRANT ALL in migration 0003 gave perch_app
    TRUNCATE on every perch table, and a TRUNCATE issued by a session
    correctly scoped to one organization erased both: 2 rows before, 0
    after, where DELETE in the same session correctly removed 1.
    """
    with admin_engine.connect() as c:
        rows = c.execute(text("""
            SELECT DISTINCT grantee, privilege_type, table_schema, table_name
              FROM information_schema.role_table_grants
             WHERE grantee IN ('gma_app','perch_app')
               AND table_schema IN ('core','perch')
               AND privilege_type IN ('TRUNCATE','REFERENCES','TRIGGER')
        """)).all()
    assert not rows, (
        "Application roles hold privileges row-level security does not "
        f"constrain: {[(r[0], r[1], f'{r[2]}.{r[3]}') for r in rows]}. "
        "TRUNCATE erases every organization's rows in one statement."
    )


def test_no_role_membership_offers_an_escalation(admin_engine):
    with admin_engine.connect() as c:
        rows = c.execute(text("""
            SELECT r.rolname, g.rolname FROM pg_roles r
              JOIN pg_auth_members m ON m.member = r.oid
              JOIN pg_roles g ON g.oid = m.roleid
             WHERE r.rolname IN ('gma_app','perch_app')
        """)).all()
    assert not rows, f"app roles are members of other roles: {rows}"


def test_no_unexpected_security_definer_functions(admin_engine):
    """Each one runs as its owner, and the owner bypasses every policy."""
    with admin_engine.connect() as c:
        rows = [f"{r[0]}.{r[1]}" for r in c.execute(text("""
            SELECT n.nspname, p.proname FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE p.prosecdef AND n.nspname IN ('core','perch')
        """)).all()]
    assert not rows, (
        f"SECURITY DEFINER functions in the tenant schemas: {rows}. Each runs "
        "with the owner's privileges and so bypasses row-level security; if "
        "one is genuinely needed, it belongs on an explicit allow-list with "
        "its columns narrowed."
    )


def test_no_materialised_views(admin_engine):
    """A matview is a stored copy, and a copy has no policies on it."""
    with admin_engine.connect() as c:
        rows = [f"{r[0]}.{r[1]}" for r in c.execute(text("""
            SELECT n.nspname, c.relname FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind = 'm' AND n.nspname IN ('core','perch')
        """)).all()]
    assert not rows, f"materialised views hold unprotected copies: {rows}"


# ==================================================================== oracles

def test_an_error_message_does_not_disclose_their_data(Session, two_organizations):
    """Colliding with a hidden row reveals that the id exists — and no more.

    This one documents a residual rather than closing it. Inserting a row
    whose primary key belongs to another organization raises a unique
    violation, which confirms that id is taken. The disclosure is bounded:
    it requires already knowing a v5 UUID, and the message repeats the value
    supplied rather than revealing any column of the hidden row. Worth
    knowing it exists; not worth breaking primary keys over.

    What this asserts is the part that would matter — that the error carries
    none of the other organization's actual data.
    """
    from sqlalchemy.exc import IntegrityError, ProgrammingError
    theirs = two_organizations[THEIRS]["grant"]
    message = ""
    with tenant_scope(OURS):
        with Session() as s:
            try:
                s.execute(text("""
                    INSERT INTO core.grants (id,tenant_id,funder_name_raw,title,status)
                    VALUES (:g,:t,'probe','probe','extracted')
                """), {"g": theirs, "t": OURS})
                s.commit()
            except (IntegrityError, ProgrammingError) as exc:
                message = str(exc)
    assert "Theirs Incorporated" not in message
    assert "theirs@example.test" not in message
    assert "theirs_secret_amount" not in message
