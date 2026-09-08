"""ORM for the shared `core` schema.

These tables are the spine described in INTEGRATION-PLAN.md: identity,
the grant record, the obligations hanging off it, document metadata and
the append-only audit log. GMA writes them; Perch reads them; neither
can reach the other's schema.

Two rules this module encodes and the rest of the app must not break:

  1. No column here can hold document text. `documents` records a
     filename and a content hash so an entry in the audit log can point
     at a source, and nothing more. The document is forgotten; the
     commitment is remembered.

  2. `grant_field_provenance.machine_value` is written once at
     extraction and never updated. A reviewer's correction goes to
     `grants` as the current truth and is echoed here as `human_value`,
     so the machine claim survives alongside it.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    ARRAY, BigInteger, Boolean, CHAR, CheckConstraint, Column, Date, DateTime,
    ForeignKey, Index, Integer, Numeric, SmallInteger, Text, UniqueConstraint,
    func, text,
)
from sqlalchemy.dialects.postgresql import CITEXT, ENUM, JSONB, UUID
from sqlalchemy.orm import relationship

from app.db import Base

# Enum types are created by migration 0001; the ORM references them.
_enum = dict(schema="core", create_type=False)

user_role_enum = ENUM("admin", "user", name="user_role", **_enum)
extraction_confidence_enum = ENUM(
    "confirmed", "inferred", "missing", name="extraction_confidence", **_enum)
document_kind_enum = ENUM(
    "proposal", "award_letter", "combined", "unknown", name="document_kind", **_enum)
grant_status_enum = ENUM(
    "extracted", "active", "closed", "cancelled", name="grant_status", **_enum)
obligation_kind_enum = ENUM(
    "report", "disbursement", "submission", "deliverable", "milestone", "meeting",
    name="obligation_kind", **_enum)
obligation_progress_enum = ENUM(
    "not_started", "in_progress", "submitted", name="obligation_progress", **_enum)
source_system_enum = ENUM(
    "donor_perfect", "charity_tracker", "excel_gl", "ehr", "award_letter", "manual",
    name="source_system", **_enum)
metric_kind_enum = ENUM("finance", "program", name="metric_kind", **_enum)
metric_sensitivity_enum = ENUM(
    "standard", "clinical", name="metric_sensitivity", **_enum)


def _pk():
    return dict(primary_key=True, default=uuid.uuid4)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), **_pk())
    name = Column(Text, nullable=False)
    slug = Column(CITEXT, nullable=False, unique=True)
    fiscal_year_start_month = Column(SmallInteger, nullable=False, server_default="1")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12",
                        name="tenants_fy_month_valid"),
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_tenant_email"),
        Index("users_tenant_idx", "tenant_id"),
    )

    id = Column(UUID(as_uuid=True), **_pk())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"),
                       nullable=False)
    email = Column(CITEXT, nullable=False)
    full_name = Column(Text)
    hashed_password = Column(Text, nullable=False)
    role = Column(user_role_enum, nullable=False, server_default="user")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    tenant = relationship("Tenant", back_populates="users")


class FunderProfile(Base):
    __tablename__ = "funder_profiles"

    id = Column(Text, primary_key=True)
    label = Column(Text, nullable=False)
    currency_format = Column(Text, nullable=False, server_default="USD_DOLLARS")
    count_format = Column(Text, nullable=False, server_default="INTEGER")
    reporting_frequency = Column(Text, nullable=False, server_default="per-report")


class Funder(Base):
    __tablename__ = "funders"

    id = Column(UUID(as_uuid=True), **_pk())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"),
                       nullable=False)
    name = Column(Text, nullable=False)
    profile_id = Column(Text, ForeignKey("core.funder_profiles.id"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("funders_tenant_name_idx", "tenant_id", text("lower(name)"), unique=True),
    )


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_metric_tenant_key"),)

    id = Column(UUID(as_uuid=True), **_pk())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"),
                       nullable=False)
    key = Column(CITEXT, nullable=False)
    label = Column(Text, nullable=False)
    kind = Column(metric_kind_enum, nullable=False)
    unit = Column(Text)
    definition = Column(Text)
    sensitivity = Column(metric_sensitivity_enum, nullable=False, server_default="standard")
    retired_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Document(Base):
    """Metadata only. There is deliberately no column for document text."""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), **_pk())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"),
                       nullable=False)
    filename = Column(Text, nullable=False)
    content_sha256 = Column(CHAR(64), nullable=False)
    byte_size = Column(BigInteger)
    document_kind = Column(document_kind_enum, nullable=False, server_default="unknown")
    document_format = Column(Text)
    extraction_method = Column(Text)
    used_external_llm = Column(Boolean, nullable=False, server_default="false")
    ocr_used = Column(Boolean, nullable=False, server_default="false")
    redaction_counts = Column(JSONB, nullable=False, server_default="{}")
    text_retained = Column(Boolean, nullable=False, server_default="false")
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("core.users.id"))
    uploaded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("text_retained = false", name="documents_no_text"),
        Index("documents_tenant_idx", "tenant_id", text("uploaded_at DESC")),
    )


class Grant(Base):
    __tablename__ = "grants"

    id = Column(UUID(as_uuid=True), **_pk())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"),
                       nullable=False)
    funder_id = Column(UUID(as_uuid=True), ForeignKey("core.funders.id"))
    funder_name_raw = Column(Text)
    title = Column(Text)
    grant_ref = Column(Text)
    purpose = Column(Text)
    amount = Column(Numeric(14, 2))
    period_start = Column(Date)
    period_end = Column(Date)
    period_raw = Column(Text)
    status = Column(grant_status_enum, nullable=False, server_default="extracted")
    extraction_method = Column(Text)
    used_external_llm = Column(Boolean, nullable=False, server_default="false")
    validation_flags = Column(ARRAY(Text), nullable=False, server_default="{}")
    data_gaps = Column(ARRAY(Text), nullable=False, server_default="{}")
    source_document_id = Column(UUID(as_uuid=True), ForeignKey("core.documents.id"))
    prospect_id = Column(UUID(as_uuid=True))
    revision = Column(Integer, nullable=False, server_default="1")
    confirmed_by = Column(UUID(as_uuid=True), ForeignKey("core.users.id"))
    confirmed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at = Column(DateTime(timezone=True))

    provenance = relationship("GrantFieldProvenance", back_populates="grant",
                              cascade="all, delete-orphan")
    contacts = relationship("GrantContact", cascade="all, delete-orphan")
    budget_lines = relationship("GrantBudgetLine", cascade="all, delete-orphan")
    workplan_tasks = relationship("GrantWorkplanTask", cascade="all, delete-orphan")
    obligations = relationship("Obligation", back_populates="grant",
                               cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status <> 'active' OR confirmed_by IS NOT NULL",
                        name="grants_confirmed_before_active"),
        CheckConstraint("period_end IS NULL OR period_start IS NULL OR period_end >= period_start",
                        name="grants_period_ordered"),
        Index("grants_tenant_status_idx", "tenant_id", "status",
              postgresql_where=text("deleted_at IS NULL")),
        Index("grants_funder_idx", "funder_id"),
    )


class GrantFieldProvenance(Base):
    __tablename__ = "grant_field_provenance"

    grant_id = Column(UUID(as_uuid=True), ForeignKey("core.grants.id", ondelete="CASCADE"),
                      primary_key=True)
    field_name = Column(Text, primary_key=True)
    machine_value = Column(Text)
    confidence = Column(extraction_confidence_enum, nullable=False, server_default="missing")
    source_kind = Column(document_kind_enum)
    quote = Column(Text)
    human_value = Column(Text)
    edited_by = Column(UUID(as_uuid=True), ForeignKey("core.users.id"))
    edited_at = Column(DateTime(timezone=True))

    grant = relationship("Grant", back_populates="provenance")

    __table_args__ = (
        CheckConstraint("(human_value IS NULL) = (edited_by IS NULL)",
                        name="provenance_edit_attributed"),
    )


class GrantContact(Base):
    __tablename__ = "grant_contacts"

    id = Column(UUID(as_uuid=True), **_pk())
    grant_id = Column(UUID(as_uuid=True), ForeignKey("core.grants.id", ondelete="CASCADE"),
                      nullable=False)
    name = Column(Text)
    title = Column(Text)
    organization = Column(Text)
    email = Column(Text)
    phone = Column(Text)
    role = Column(Text)


class GrantBudgetLine(Base):
    __tablename__ = "grant_budget_lines"

    id = Column(UUID(as_uuid=True), **_pk())
    grant_id = Column(UUID(as_uuid=True), ForeignKey("core.grants.id", ondelete="CASCADE"),
                      nullable=False)
    category = Column(Text, nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    description = Column(Text)
    timeline_hint = Column(Text)
    account_code = Column(Text)
    sort_order = Column(Integer, nullable=False, server_default="0")


class GrantWorkplanTask(Base):
    __tablename__ = "grant_workplan_tasks"

    id = Column(UUID(as_uuid=True), **_pk())
    grant_id = Column(UUID(as_uuid=True), ForeignKey("core.grants.id", ondelete="CASCADE"),
                      nullable=False)
    task_name = Column(Text, nullable=False)
    description = Column(Text)
    start_date = Column(Date)
    end_date = Column(Date)
    responsible_party = Column(Text)
    deliverables = Column(Text)
    sort_order = Column(Integer, nullable=False, server_default="0")


class Obligation(Base):
    """GMA reporting/submission requirements and Perch deadlines, one table."""
    __tablename__ = "obligations"

    id = Column(UUID(as_uuid=True), **_pk())
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"),
                       nullable=False)
    grant_id = Column(UUID(as_uuid=True), ForeignKey("core.grants.id", ondelete="CASCADE"),
                      nullable=False)
    kind = Column(obligation_kind_enum, nullable=False)
    title = Column(Text, nullable=False)
    due_date = Column(Date)
    due_date_raw = Column(Text)
    recurrence_rule = Column(Text)
    amount = Column(Numeric(14, 2))
    lead_time_days = Column(Integer, nullable=False, server_default="7")
    next_day_follow_up = Column(Boolean, nullable=False, server_default="true")
    instructions = Column(Text)
    required_elements = Column(ARRAY(Text), nullable=False, server_default="{}")
    reporting_period = Column(Text)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("core.users.id"))
    owner_label = Column(Text)
    progress = Column(obligation_progress_enum, nullable=False, server_default="not_started")
    submitted_at = Column(DateTime(timezone=True))
    origin = Column(source_system_enum, nullable=False, server_default="award_letter")
    source_document_id = Column(UUID(as_uuid=True), ForeignKey("core.documents.id"))
    confidence = Column(extraction_confidence_enum, nullable=False, server_default="inferred")
    quote = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at = Column(DateTime(timezone=True))

    grant = relationship("Grant", back_populates="obligations")
    criteria = relationship("ObligationCriterion", cascade="all, delete-orphan")

    __table_args__ = (
        # See migrations/sql/0001_core.sql: an undated obligation with its
        # raw text preserved is a reviewer's to-do, not a reason to drop it.
        CheckConstraint(
            "due_date IS NOT NULL OR recurrence_rule IS NOT NULL "
            "OR due_date_raw IS NOT NULL",
            name="obligations_has_timing"),
        Index("obligations_grant_idx", "grant_id",
              postgresql_where=text("deleted_at IS NULL")),
        Index("obligations_due_idx", "tenant_id", "due_date",
              postgresql_where=text("deleted_at IS NULL")),
    )


class ObligationCriterion(Base):
    __tablename__ = "obligation_criteria"

    id = Column(UUID(as_uuid=True), **_pk())
    obligation_id = Column(UUID(as_uuid=True),
                           ForeignKey("core.obligations.id", ondelete="CASCADE"),
                           nullable=False)
    text = Column(Text, nullable=False)
    metric_id = Column(UUID(as_uuid=True), ForeignKey("core.metric_definitions.id"))
    frequency = Column(Text, nullable=False, server_default="per-report")
    format_hint = Column(Text)
    sort_order = Column(Integer, nullable=False, server_default="0")


class AuditLog(Base):
    """Append-only. The database REVOKEs UPDATE and DELETE from both app roles."""
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenants.id"), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("core.users.id"))
    actor_label = Column(Text)
    action = Column(Text, nullable=False)
    entity_schema = Column(Text, nullable=False)
    entity_table = Column(Text, nullable=False)
    entity_id = Column(UUID(as_uuid=True))
    period_id = Column(UUID(as_uuid=True))
    field = Column(Text)
    old_value = Column(Text)
    new_value = Column(Text)
    source_document_id = Column(UUID(as_uuid=True), ForeignKey("core.documents.id"))
    request_id = Column(Text)

    __table_args__ = (
        Index("audit_log_tenant_time_idx", "tenant_id", text("occurred_at DESC")),
        Index("audit_log_entity_idx", "entity_table", "entity_id"),
    )


__all__ = [
    "Tenant", "User", "FunderProfile", "Funder", "MetricDefinition", "Document",
    "Grant", "GrantFieldProvenance", "GrantContact", "GrantBudgetLine",
    "GrantWorkplanTask", "Obligation", "ObligationCriterion", "AuditLog",
]
