-- =====================================================================
-- perch: reporting periods and the fact tables.  Perch only.
--
-- Phase 3 of the Perch/GMA integration.  Until now Perch kept its own
-- state in snapshots.json, which a container filesystem does not
-- survive.  These are the tables that replace it, lifted from
-- grant-platform/schema.sql so the two stay diffable.
--
-- core.v_upcoming_obligations is NOT created here: migration 0001
-- already creates it.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS perch;


-- Locale-independent 'Mon YYYY'.  to_char() is only STABLE (it reads
-- lc_time), so it cannot back a generated column — and a label that
-- shifts with server locale would break Perch's ^[A-Z][a-z]{2} \d{4}$
-- period format anyway.
CREATE FUNCTION perch.period_label(d date) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT (ARRAY['Jan','Feb','Mar','Apr','May','Jun',
                  'Jul','Aug','Sep','Oct','Nov','Dec'])
               [extract(month from d)::int]
           || ' ' || extract(year from d)::text
$$;


-- Settles SECURITY_FINDINGS §7.1 in favour of "rows carry their own
-- period".  period_label is derived, not a key.
CREATE TABLE perch.reporting_periods (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid        NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    period_start date        NOT NULL,
    period_label text        GENERATED ALWAYS AS (perch.period_label(period_start)) STORED,
    fiscal_year  integer,
    closed_at    timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, period_start),
    CONSTRAINT periods_month_aligned CHECK (date_trunc('month', period_start) = period_start)
);


-- Fact tables are APPEND-ONLY.  A correction inserts a new row and
-- stamps superseded_at on the old one (SECURITY_FINDINGS §7.5: the
-- current merge path is "actively destructive of history").  The
-- partial unique index keeps "what is the number now" a one-row lookup.
--
-- is_synthetic closes §7.4: pilot figures can no longer be reported as
-- real.  deleted_at gives the deletion path that 815 ILCS 530/40
-- secure disposal requires and the JSON store never had.

CREATE TABLE perch.finance_facts (
    id            uuid               PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid               NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    period_id     uuid               NOT NULL REFERENCES perch.reporting_periods(id),
    metric_id     uuid               NOT NULL REFERENCES core.metric_definitions(id),
    grant_id      uuid               REFERENCES core.grants(id),
    month_value   numeric(14,2)      NOT NULL DEFAULT 0,
    ytd_value     numeric(14,2)      NOT NULL DEFAULT 0,
    budget_ytd    numeric(14,2)      NOT NULL DEFAULT 0,
    source        core.source_system NOT NULL DEFAULT 'manual',
    document_id   uuid               REFERENCES core.documents(id),
    is_synthetic  boolean            NOT NULL DEFAULT false,
    recorded_at   timestamptz        NOT NULL DEFAULT now(),
    recorded_by   uuid               REFERENCES core.users(id),
    -- A correction stamps superseded_at (which releases the partial
    -- unique index below) and points superseded_by at its replacement.
    -- The self-FK is deferred so both happen in one transaction.
    superseded_at timestamptz,
    superseded_by uuid               REFERENCES perch.finance_facts(id)
                                     DEFERRABLE INITIALLY DEFERRED,
    deleted_at    timestamptz
);
CREATE UNIQUE INDEX finance_facts_current_idx
    ON perch.finance_facts (period_id, metric_id)
    WHERE superseded_at IS NULL AND deleted_at IS NULL;

CREATE TABLE perch.program_facts (
    id            uuid               PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid               NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    period_id     uuid               NOT NULL REFERENCES perch.reporting_periods(id),
    metric_id     uuid               NOT NULL REFERENCES core.metric_definitions(id),
    grant_id      uuid               REFERENCES core.grants(id),
    month_value   numeric(14,2)      NOT NULL DEFAULT 0,
    ytd_value     numeric(14,2)      NOT NULL DEFAULT 0,
    annual_goal   numeric(14,2)      NOT NULL DEFAULT 0,
    source        core.source_system NOT NULL DEFAULT 'manual',
    document_id   uuid               REFERENCES core.documents(id),
    -- SECURITY_FINDINGS H-7: distinct-person counts below 5 are a
    -- disclosure risk; flag them at write time rather than at export.
    small_cell    boolean            GENERATED ALWAYS AS
                                     (ytd_value > 0 AND ytd_value < 5) STORED,
    is_synthetic  boolean            NOT NULL DEFAULT false,
    recorded_at   timestamptz        NOT NULL DEFAULT now(),
    recorded_by   uuid               REFERENCES core.users(id),
    superseded_at timestamptz,
    superseded_by uuid               REFERENCES perch.program_facts(id)
                                     DEFERRABLE INITIALLY DEFERRED,
    deleted_at    timestamptz
);
CREATE UNIQUE INDEX program_facts_current_idx
    ON perch.program_facts (period_id, metric_id)
    WHERE superseded_at IS NULL AND deleted_at IS NULL;

CREATE TABLE perch.revenue_facts (
    id                        uuid               PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                 uuid               NOT NULL REFERENCES core.tenants(id) ON DELETE CASCADE,
    period_id                 uuid               NOT NULL REFERENCES perch.reporting_periods(id),
    -- How the donut chart stops being a pile of strings.
    grant_id                  uuid               REFERENCES core.grants(id),
    label                     text               NOT NULL,
    amount                    numeric(14,2)      NOT NULL DEFAULT 0,
    source                    core.source_system NOT NULL DEFAULT 'donor_perfect',
    -- H-7: DonorPerfect fund/campaign labels routinely carry donor
    -- names paired with exact amounts.  Flag so exports can exclude
    -- them without inspecting every label.
    contains_donor_identifier boolean            NOT NULL DEFAULT false,
    document_id               uuid               REFERENCES core.documents(id),
    is_synthetic              boolean            NOT NULL DEFAULT false,
    recorded_at               timestamptz        NOT NULL DEFAULT now(),
    recorded_by               uuid               REFERENCES core.users(id),
    superseded_at             timestamptz,
    superseded_by             uuid               REFERENCES perch.revenue_facts(id)
                                                 DEFERRABLE INITIALLY DEFERRED,
    deleted_at                timestamptz
);
CREATE UNIQUE INDEX revenue_facts_current_idx
    ON perch.revenue_facts (period_id, lower(label))
    WHERE superseded_at IS NULL AND deleted_at IS NULL;

-- Was funder_profiles.json "field_aliases".  Keyed on metric ID, so
-- renaming a canonical metric no longer silently breaks the mapping.
CREATE TABLE perch.funder_field_aliases (
    profile_id        text NOT NULL REFERENCES core.funder_profiles(id) ON DELETE CASCADE,
    metric_id         uuid NOT NULL REFERENCES core.metric_definitions(id) ON DELETE CASCADE,
    funder_field_name text NOT NULL,
    PRIMARY KEY (profile_id, metric_id)
);


-- =====================================================================
-- Views
-- =====================================================================

CREATE VIEW perch.v_current_finance AS
SELECT f.*, m.key AS metric_key, m.label AS metric_label,
       p.period_start, p.period_label,
       round(f.ytd_value - f.budget_ytd, 2) AS variance
FROM perch.finance_facts f
JOIN core.metric_definitions m ON m.id = f.metric_id
JOIN perch.reporting_periods p ON p.id = f.period_id
WHERE f.superseded_at IS NULL AND f.deleted_at IS NULL;

CREATE VIEW perch.v_current_program AS
SELECT f.*, m.key AS metric_key, m.label AS metric_label,
       p.period_start, p.period_label,
       CASE WHEN f.annual_goal = 0 THEN NULL
            ELSE round(f.ytd_value / f.annual_goal, 4) END AS pct_to_goal
FROM perch.program_facts f
JOIN core.metric_definitions m ON m.id = f.metric_id
JOIN perch.reporting_periods p ON p.id = f.period_id
WHERE f.superseded_at IS NULL AND f.deleted_at IS NULL;

-- Small-cell suppression as structure, not as a flag someone has to
-- remember.  Anything leaving the building for a funder report, a board
-- deck or an annual report reads THIS view, never v_current_program.
CREATE VIEW perch.v_program_for_export AS
SELECT period_id, period_start, period_label, metric_id, metric_key, metric_label,
       CASE WHEN small_cell THEN NULL ELSE month_value END AS month_value,
       CASE WHEN small_cell THEN NULL ELSE ytd_value   END AS ytd_value,
       annual_goal,
       CASE WHEN small_cell THEN NULL ELSE pct_to_goal END AS pct_to_goal,
       small_cell AS suppressed,
       is_synthetic
FROM perch.v_current_program;

CREATE VIEW perch.v_current_revenue AS
SELECT f.*, p.period_start, p.period_label
FROM perch.revenue_facts f
JOIN perch.reporting_periods p ON p.id = f.period_id
WHERE f.superseded_at IS NULL AND f.deleted_at IS NULL;


-- =====================================================================
-- Grants
--
-- The enforceable form of "no donor or client data ever reaches a
-- prompt": the service that holds the OpenAI credential cannot read a
-- single donor label or program outcome.
-- =====================================================================

GRANT USAGE ON SCHEMA perch TO perch_app;
GRANT ALL ON ALL TABLES IN SCHEMA perch TO perch_app;

REVOKE ALL ON SCHEMA perch FROM gma_app;
REVOKE ALL ON ALL TABLES IN SCHEMA perch FROM gma_app;
