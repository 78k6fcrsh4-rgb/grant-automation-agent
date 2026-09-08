-- Migration 0001: the shared `core` schema.
--
-- This file is the EXECUTABLE source of truth for what is deployed.
-- Its design reference is grant-platform/schema.sql; the `perch` schema
-- and its grants land in Phase 3, not here.

CREATE EXTENSION IF NOT EXISTS citext;
CREATE SCHEMA IF NOT EXISTS core;

-- Roles are cluster-wide and shared by every organization's database,
-- so creation is guarded rather than unconditional.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gma_app') THEN
        CREATE ROLE gma_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'perch_app') THEN
        CREATE ROLE perch_app LOGIN;
    END IF;
END
$$;

CREATE TYPE core.extraction_confidence AS ENUM ('confirmed', 'inferred', 'missing');
CREATE TYPE core.document_kind        AS ENUM ('proposal', 'award_letter', 'combined', 'unknown');
CREATE TYPE core.grant_status         AS ENUM ('extracted', 'active', 'closed', 'cancelled');
CREATE TYPE core.obligation_kind      AS ENUM
    ('report', 'disbursement', 'submission', 'deliverable', 'milestone', 'meeting');
CREATE TYPE core.obligation_progress  AS ENUM ('not_started', 'in_progress', 'submitted');
CREATE TYPE core.source_system        AS ENUM
    ('donor_perfect', 'charity_tracker', 'excel_gl', 'ehr', 'award_letter', 'manual');
CREATE TYPE core.metric_kind          AS ENUM ('finance', 'program');
CREATE TYPE core.metric_sensitivity   AS ENUM ('standard', 'clinical');
-- 'user', not 'member': GProspect's spelling, so the third app joins
-- without a rename.
CREATE TYPE core.user_role            AS ENUM ('admin', 'user');

CREATE TABLE core.tenants (
    id                      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    text        NOT NULL,
    slug                    citext      NOT NULL UNIQUE,
    fiscal_year_start_month smallint    NOT NULL DEFAULT 1
                                        CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE core.users (
    id              uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid           NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    email           citext         NOT NULL,
    full_name       text,
    hashed_password text           NOT NULL,
    role            core.user_role NOT NULL DEFAULT 'user',
    is_active       boolean        NOT NULL DEFAULT true,
    created_at      timestamptz    NOT NULL DEFAULT now(),
    CONSTRAINT uq_tenant_email UNIQUE (tenant_id, email)
);
CREATE INDEX users_tenant_idx ON core.users (tenant_id);

CREATE TABLE core.funder_profiles (
    id                  text PRIMARY KEY,
    label               text NOT NULL,
    currency_format     text NOT NULL DEFAULT 'USD_DOLLARS'
                             CHECK (currency_format IN
                                    ('USD_DOLLARS', 'USD_CENTS', 'USD_DOLLARS_ROUNDED')),
    count_format        text NOT NULL DEFAULT 'INTEGER',
    reporting_frequency text NOT NULL DEFAULT 'per-report'
                             CHECK (reporting_frequency IN
                                    ('monthly', 'quarterly', 'annual', 'per-report'))
);

CREATE TABLE core.funders (
    id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  uuid        NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    name       text        NOT NULL,
    profile_id text        REFERENCES core.funder_profiles(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX funders_tenant_name_idx ON core.funders (tenant_id, lower(name));

CREATE TABLE core.metric_definitions (
    id          uuid                    PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid                    NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    key         citext                  NOT NULL,
    label       text                    NOT NULL,
    kind        core.metric_kind        NOT NULL,
    unit        text,
    definition  text,
    sensitivity core.metric_sensitivity NOT NULL DEFAULT 'standard',
    retired_at  timestamptz,
    created_at  timestamptz             NOT NULL DEFAULT now(),
    CONSTRAINT uq_metric_tenant_key UNIQUE (tenant_id, key)
);

-- Metadata only: there is deliberately no column that can hold document
-- text, and text_retained is a tripwire for anyone who adds one.
CREATE TABLE core.documents (
    id                uuid               PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid               NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    filename          text               NOT NULL,
    content_sha256    char(64)           NOT NULL,
    byte_size         bigint,
    document_kind     core.document_kind NOT NULL DEFAULT 'unknown',
    document_format   text,
    extraction_method text,
    used_external_llm boolean            NOT NULL DEFAULT false,
    ocr_used          boolean            NOT NULL DEFAULT false,
    redaction_counts  jsonb              NOT NULL DEFAULT '{}'::jsonb,
    text_retained     boolean            NOT NULL DEFAULT false,
    uploaded_by       uuid               REFERENCES core.users(id),
    uploaded_at       timestamptz        NOT NULL DEFAULT now(),
    CONSTRAINT documents_no_text CHECK (text_retained = false)
);
CREATE INDEX documents_tenant_idx ON core.documents (tenant_id, uploaded_at DESC);

CREATE TABLE core.grants (
    id                 uuid              PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid              NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    funder_id          uuid              REFERENCES core.funders(id),
    funder_name_raw    text,
    title              text,
    grant_ref          text,
    purpose            text,
    amount             numeric(14,2),
    period_start       date,
    period_end         date,
    period_raw         text,
    status             core.grant_status NOT NULL DEFAULT 'extracted',
    extraction_method  text,
    used_external_llm  boolean           NOT NULL DEFAULT false,
    validation_flags   text[]            NOT NULL DEFAULT '{}',
    data_gaps          text[]            NOT NULL DEFAULT '{}',
    source_document_id uuid              REFERENCES core.documents(id),
    prospect_id        uuid,
    revision           integer           NOT NULL DEFAULT 1,
    confirmed_by       uuid              REFERENCES core.users(id),
    confirmed_at       timestamptz,
    created_at         timestamptz       NOT NULL DEFAULT now(),
    updated_at         timestamptz       NOT NULL DEFAULT now(),
    deleted_at         timestamptz,
    CONSTRAINT grants_confirmed_before_active
        CHECK (status <> 'active' OR confirmed_by IS NOT NULL),
    CONSTRAINT grants_period_ordered
        CHECK (period_end IS NULL OR period_start IS NULL OR period_end >= period_start)
);
CREATE INDEX grants_tenant_status_idx ON core.grants (tenant_id, status) WHERE deleted_at IS NULL;
CREATE INDEX grants_funder_idx        ON core.grants (funder_id);

CREATE TABLE core.grant_field_provenance (
    grant_id      uuid                       NOT NULL REFERENCES core.grants(id) ON DELETE CASCADE,
    field_name    text                       NOT NULL,
    machine_value text,
    confidence    core.extraction_confidence NOT NULL DEFAULT 'missing',
    source_kind   core.document_kind,
    quote         text,
    human_value   text,
    edited_by     uuid                       REFERENCES core.users(id),
    edited_at     timestamptz,
    PRIMARY KEY (grant_id, field_name),
    CONSTRAINT provenance_edit_attributed
        CHECK ((human_value IS NULL) = (edited_by IS NULL))
);

CREATE TABLE core.grant_contacts (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    grant_id     uuid NOT NULL REFERENCES core.grants(id) ON DELETE CASCADE,
    name         text,
    title        text,
    organization text,
    email        text,
    phone        text,
    role         text
);

CREATE TABLE core.grant_budget_lines (
    id            uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    grant_id      uuid          NOT NULL REFERENCES core.grants(id) ON DELETE CASCADE,
    category      text          NOT NULL,
    amount        numeric(14,2) NOT NULL,
    description   text,
    timeline_hint text,
    account_code  text,
    sort_order    integer       NOT NULL DEFAULT 0
);

CREATE TABLE core.grant_workplan_tasks (
    id                uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
    grant_id          uuid    NOT NULL REFERENCES core.grants(id) ON DELETE CASCADE,
    task_name         text    NOT NULL,
    description       text,
    start_date        date,
    end_date          date,
    responsible_party text,
    deliverables      text,
    sort_order        integer NOT NULL DEFAULT 0
);

CREATE TABLE core.obligations (
    id                 uuid                       PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid                       NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    grant_id           uuid                       NOT NULL REFERENCES core.grants(id) ON DELETE CASCADE,
    kind               core.obligation_kind       NOT NULL,
    title              text                       NOT NULL,
    due_date           date,
    due_date_raw       text,
    recurrence_rule    text,
    amount             numeric(14,2),
    lead_time_days     integer                    NOT NULL DEFAULT 7,
    next_day_follow_up boolean                    NOT NULL DEFAULT true,
    instructions       text,
    required_elements  text[]                     NOT NULL DEFAULT '{}',
    reporting_period   text,
    owner_user_id      uuid                       REFERENCES core.users(id),
    owner_label        text,
    progress           core.obligation_progress   NOT NULL DEFAULT 'not_started',
    submitted_at       timestamptz,
    origin             core.source_system         NOT NULL DEFAULT 'award_letter',
    source_document_id uuid                       REFERENCES core.documents(id),
    confidence         core.extraction_confidence NOT NULL DEFAULT 'inferred',
    quote              text,
    created_at         timestamptz                NOT NULL DEFAULT now(),
    updated_at         timestamptz                NOT NULL DEFAULT now(),
    deleted_at         timestamptz,
    -- An obligation must carry SOME timing. A parsed date or a recurrence
    -- rule is schedulable; due_date_raw alone means the extractor found a
    -- requirement it could not date ("90 days after the period ends"), which
    -- a reviewer must resolve. Dropping those silently would lose real
    -- obligations, so they are stored undated and surfaced instead.
    CONSTRAINT obligations_has_timing
        CHECK (due_date IS NOT NULL OR recurrence_rule IS NOT NULL
               OR due_date_raw IS NOT NULL)
);
CREATE INDEX obligations_due_idx   ON core.obligations (tenant_id, due_date) WHERE deleted_at IS NULL;
CREATE INDEX obligations_grant_idx ON core.obligations (grant_id)            WHERE deleted_at IS NULL;

CREATE TABLE core.obligation_criteria (
    id            uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
    obligation_id uuid    NOT NULL REFERENCES core.obligations(id) ON DELETE CASCADE,
    text          text    NOT NULL,
    metric_id     uuid    REFERENCES core.metric_definitions(id),
    frequency     text    NOT NULL DEFAULT 'per-report',
    format_hint   text,
    sort_order    integer NOT NULL DEFAULT 0
);

CREATE TABLE core.audit_log (
    id                 bigserial   PRIMARY KEY,
    tenant_id          uuid        NOT NULL REFERENCES core.tenants(id),
    occurred_at        timestamptz NOT NULL DEFAULT now(),
    actor_user_id      uuid        REFERENCES core.users(id),
    actor_label        text,
    action             text        NOT NULL,
    entity_schema      text        NOT NULL,
    entity_table       text        NOT NULL,
    entity_id          uuid,
    period_id          uuid,
    field              text,
    old_value          text,
    new_value          text,
    source_document_id uuid        REFERENCES core.documents(id),
    request_id         text
);
CREATE INDEX audit_log_tenant_time_idx ON core.audit_log (tenant_id, occurred_at DESC);
CREATE INDEX audit_log_entity_idx      ON core.audit_log (entity_table, entity_id);

CREATE VIEW core.v_upcoming_obligations AS
SELECT o.id, o.tenant_id, o.kind, o.title, o.due_date, o.progress,
       o.amount, o.required_elements,
       g.id    AS grant_id,
       g.title AS grant_title,
       COALESCE(f.name, g.funder_name_raw) AS funder_name,
       f.profile_id,
       u.full_name AS owner_name
FROM core.obligations o
JOIN core.grants g       ON g.id = o.grant_id
LEFT JOIN core.funders f ON f.id = g.funder_id
LEFT JOIN core.users   u ON u.id = o.owner_user_id
WHERE o.deleted_at IS NULL
  AND g.deleted_at IS NULL
  AND g.status = 'active';

CREATE VIEW core.v_extraction_overrides AS
SELECT p.grant_id, g.title AS grant_title, p.field_name,
       p.machine_value, p.human_value, p.confidence, p.quote,
       u.email AS edited_by_email, p.edited_at
FROM core.grant_field_provenance p
JOIN core.grants g      ON g.id = p.grant_id
LEFT JOIN core.users u  ON u.id = p.edited_by
WHERE p.human_value IS NOT NULL
  AND p.human_value IS DISTINCT FROM p.machine_value;

-- Carry over any accounts from the pre-2.8.0 public-schema tables, if a
-- Postgres deployment already had them. New UUIDs are minted; password
-- hashes and the tenant relationship survive. 'member' becomes 'user'.
DO $$
BEGIN
    IF to_regclass('public.tenants') IS NOT NULL
       AND to_regclass('public.users') IS NOT NULL THEN
        CREATE TEMP TABLE _tenant_map AS
            SELECT t.id AS old_id, gen_random_uuid() AS new_id, t.name, t.slug
            FROM public.tenants t;
        INSERT INTO core.tenants (id, name, slug)
            SELECT new_id, name, slug FROM _tenant_map;
        INSERT INTO core.users (tenant_id, email, full_name, hashed_password, role, is_active)
            SELECT m.new_id, u.email, u.full_name, u.hashed_password,
                   (CASE WHEN u.role = 'admin' THEN 'admin' ELSE 'user' END)::core.user_role,
                   COALESCE(u.is_active, true)
            FROM public.users u JOIN _tenant_map m ON m.old_id = u.tenant_id;
        RAISE NOTICE 'Carried over % legacy accounts from public.users',
            (SELECT count(*) FROM public.users);
    END IF;
END
$$;

GRANT USAGE ON SCHEMA core TO gma_app, perch_app;

GRANT SELECT, INSERT, UPDATE ON
    core.tenants, core.users, core.funders, core.documents,
    core.grants, core.grant_field_provenance, core.grant_contacts,
    core.grant_budget_lines, core.grant_workplan_tasks,
    core.obligations, core.obligation_criteria
TO gma_app;
GRANT SELECT ON core.funder_profiles, core.metric_definitions,
                core.v_extraction_overrides TO gma_app;
GRANT INSERT ON core.audit_log TO gma_app;
GRANT USAGE  ON SEQUENCE core.audit_log_id_seq TO gma_app;

GRANT SELECT ON
    core.tenants, core.users, core.funders, core.funder_profiles,
    core.grants, core.grant_field_provenance, core.grant_contacts,
    core.grant_budget_lines, core.grant_workplan_tasks,
    core.documents, core.obligations, core.obligation_criteria,
    core.v_upcoming_obligations
TO perch_app;
GRANT SELECT, INSERT, UPDATE ON core.metric_definitions TO perch_app;
GRANT INSERT ON core.audit_log TO perch_app;
GRANT USAGE  ON SEQUENCE core.audit_log_id_seq TO perch_app;
-- Perch may advance a deadline, not invent one.
GRANT UPDATE (progress, owner_user_id, submitted_at, updated_at)
    ON core.obligations TO perch_app;

-- Append-only audit log, for everyone.
REVOKE UPDATE, DELETE ON core.audit_log FROM gma_app, perch_app;
