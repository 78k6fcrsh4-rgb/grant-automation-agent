"""What crosses from an extraction session into the database, and what never does.

These are the tests that keep GMA's "forget by design" promise honest once
persistence exists: the document is forgotten, the commitment is remembered.
"""
import os

import pytest

from tests.conftest import TEST_DATABASE_URL, migrate_test_database, needs_db

if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("SECRET_KEY", "test-secret-persistence")
os.environ.setdefault("AUTO_MIGRATE", "false")

from app.models.schemas import (  # noqa: E402
    Budget, BudgetItem, ContactInfo, GrantData, ReportingRequirement,
    SubmissionRequirement, Timeline, TimelineItem, TransmissionPreview,
    WorkPlan, WorkPlanTask,
)
from app.services.grant_persistence import (  # noqa: E402
    DocumentTextLeak, assert_no_leak, parse_date, parse_period,
)
from app.services.grant_repository import (  # noqa: E402
    EPHEMERAL, LINKED, build_repository,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def sample_grant_data() -> GrantData:
    return GrantData(
        raw_text="CONFIDENTIAL AWARD LETTER BODY " * 40,
        proposal_text="proposal body text that is comfortably long enough to match",
        award_letter_text="award letter body text that is comfortably long enough",
        redacted_text="redacted body text that is comfortably long enough to match",
        transmission_preview=TransmissionPreview(
            payload_excerpt="an excerpt of the letter long enough to be detectable"),
        organization_name="Milton Township",
        funder_name="DuPage Health Coalition",
        grant_title="Community Health Access",
        grant_amount=150000.0,
        grant_period="July 1, 2026 - June 30, 2027",
        purpose="Expand access to care",
        extraction_confidence={"grant_amount": "inferred", "funder_name": "confirmed"},
        validation_flags=["Amount appears only in a threshold clause"],
        extraction_method="llm+regex",
        used_external_llm=True,
        contacts=[ContactInfo(name="A. Officer", role="program_officer")],
        budget=Budget(total_grant_amount=150000.0,
                      items=[BudgetItem(category="Personnel", amount=90000.0)]),
        workplan=WorkPlan(tasks=[WorkPlanTask(
            task_name="Hire navigator", description="d",
            start_date="July 1, 2026", end_date="sometime later")]),
        reporting_requirements=[
            ReportingRequirement(period="quarterly", due_date="2027-03-31",
                                 description="Interim report",
                                 required_elements=["financial summary"]),
            ReportingRequirement(period="annual",
                                 due_date="90 days after the period ends",
                                 description="Final report"),
        ],
        submission_requirements=[SubmissionRequirement(
            category="reimbursement", due_date="12/31/2026",
            instructions="Submit via portal")],
        timeline=Timeline(items=[
            # Same obligation the interim reporting requirement describes.
            TimelineItem(date="March 31, 2027", description="Interim report due",
                         category="report"),
            TimelineItem(date="June 1, 2027", description="Payment 2",
                         category="payment", amount="$50,000"),
            TimelineItem(date="whenever", description="Uncategorised"),
        ]),
    )


# ---- pure functions, no database ------------------------------------------

def test_dates_are_parsed_but_never_guessed():
    assert parse_date("March 31, 2027").isoformat() == "2027-03-31"
    assert parse_date("12/31/2026").isoformat() == "2026-12-31"
    assert parse_date("2027-03-31").isoformat() == "2027-03-31"
    # A date the extractor could not resolve must stay unresolved rather
    # than becoming a plausible-looking wrong one.
    assert parse_date("90 days after the period ends") is None
    assert parse_date("") is None


def test_period_range_is_split():
    start, end = parse_period("July 1, 2026 - June 30, 2027")
    assert start.isoformat() == "2026-07-01"
    assert end.isoformat() == "2027-06-30"


def test_leak_guard_detects_document_text_in_a_payload():
    grant_data = sample_grant_data()
    with pytest.raises(DocumentTextLeak):
        assert_no_leak(grant_data, ["Community Health Access", grant_data.raw_text[:200]])


def test_leak_guard_passes_a_clean_payload():
    assert_no_leak(sample_grant_data(),
                   ["Community Health Access", "Expand access to care", None, 42])


# ---- against a real database ----------------------------------------------

@pytest.fixture(scope="module")
def db_session():
    migrate_test_database(TEST_DATABASE_URL)
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="module")
def tenant_and_user(db_session):
    from app.models import core_models as cm
    tenant = cm.Tenant(name="DuPage Health Coalition", slug="dupage")
    db_session.add(tenant)
    db_session.flush()
    user = cm.User(tenant_id=tenant.id, email="parker@example.org",
                   full_name="Parker", hashed_password="x", role="admin")
    db_session.add(user)
    db_session.commit()
    return tenant, user


@needs_db
def test_ephemeral_mode_files_nothing(db_session, tenant_and_user):
    from app.models import core_models as cm
    tenant, user = tenant_and_user
    before = db_session.query(cm.Grant).count()

    repo = build_repository(EPHEMERAL)
    repo.put("pkg-eph", sample_grant_data(), tenant.id)
    assert repo.persists is False
    assert repo.confirm("pkg-eph", tenant_id=tenant.id, user_id=user.id,
                        db=db_session) is None
    assert db_session.query(cm.Grant).count() == before


@needs_db
def test_linked_mode_files_the_record_with_the_edit_trail(db_session, tenant_and_user):
    from app.models import core_models as cm
    tenant, user = tenant_and_user
    grant_data = sample_grant_data()

    repo = build_repository(LINKED)
    repo.put("pkg-linked", grant_data, tenant.id)
    # The reviewer corrects the flagged amount before confirming.
    grant_data.grant_amount = 133600.0
    repo.record_edit("pkg-linked", "grant_amount", user.id)
    grant_id = repo.confirm("pkg-linked", tenant_id=tenant.id, user_id=user.id,
                            db=db_session)
    assert grant_id is not None

    grant = db_session.query(cm.Grant).filter(cm.Grant.id == grant_id).one()
    assert str(grant.amount) == "133600.00"
    assert grant.status == "active" and grant.confirmed_by == user.id
    assert grant.period_start.isoformat() == "2026-07-01"
    assert grant.period_end.isoformat() == "2027-06-30"
    assert grant.revision == 2

    prov = {p.field_name: p for p in grant.provenance}
    # The extractor's claim survives the correction rather than being
    # overwritten by it — otherwise nothing records that it was wrong.
    assert prov["grant_amount"].machine_value == "150000.0"
    assert prov["grant_amount"].human_value == "133600.0"
    assert prov["grant_amount"].confidence == "confirmed"
    assert prov["grant_amount"].edited_by == user.id
    assert prov["funder_name"].human_value is None

    audits = db_session.query(cm.AuditLog).all()
    assert any(a.field == "grant_amount" and a.old_value == "150000.0" for a in audits)


@needs_db
def test_obligations_are_deduplicated_and_undated_ones_survive(db_session, tenant_and_user):
    from app.models import core_models as cm
    tenant, user = tenant_and_user

    repo = build_repository(LINKED)
    repo.put("pkg-obl", sample_grant_data(), tenant.id)
    grant_id = repo.confirm("pkg-obl", tenant_id=tenant.id, user_id=user.id,
                            db=db_session)
    obligations = db_session.query(cm.Obligation).filter(
        cm.Obligation.grant_id == grant_id).all()

    # The interim report appears as both a requirement and a timeline entry;
    # two identical deadlines would mean two calendar events in Perch.
    report_dates = [o.due_date for o in obligations
                    if o.kind == "report" and o.due_date]
    assert len(report_dates) == len(set(report_dates))

    # A requirement the extractor could not date is a reviewer's to-do, not
    # something to drop on the floor.
    undated = [o for o in obligations if o.due_date is None]
    assert undated and undated[0].due_date_raw == "90 days after the period ends"

    # An uncategorised timeline entry is not an obligation.
    assert not any(o.title == "Uncategorised" for o in obligations)
    assert any(o.kind == "disbursement" and o.amount for o in obligations)


@needs_db
def test_core_has_no_column_that_could_hold_document_text(db_session):
    from sqlalchemy import text
    rows = db_session.execute(text("""
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = 'core'
          AND column_name IN ('raw_text', 'proposal_text', 'award_letter_text',
                              'redacted_text', 'payload_excerpt')
    """)).fetchall()
    assert rows == []
