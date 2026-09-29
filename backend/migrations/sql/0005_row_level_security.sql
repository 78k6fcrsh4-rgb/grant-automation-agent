-- =====================================================================
-- Many organizations in one database, separated by row-level security.
--
-- This replaces the isolation model the platform was built on. Until now
-- one database held one organization, so Postgres could not join across
-- them without an explicit FDW and a missed tenant filter failed closed
-- with "relation does not exist". That guarantee was structural: it held
-- whatever the application code did.
--
-- From here the guarantee is a policy. Every row of every organization
-- sits in the same tables, and separation holds only while each database
-- session sets app.tenant_id correctly, in every code path. The tests in
-- grant_backend/tests and backend/tests are what make that true; they are
-- not optional and no second organization's data should be loaded until
-- they pass AS THE APP ROLE.
--
-- WHY THERE IS NO `FORCE` AND NO BYPASSRLS MIGRATOR
--
-- The plan called for FORCE ROW LEVEL SECURITY plus a migrator role
-- holding BYPASSRLS. Neither is available here, and the reason is worth
-- recording rather than rediscovering:
--
--   * Only a role that already has BYPASSRLS may create or grant it, and
--     that means a superuser. On Azure Flexible Server the admin login is
--     NOT a superuser (verified: "permission denied to create role /
--     Only roles with the BYPASSRLS attribute may create roles with the
--     BYPASSRLS attribute"). A migrator role is therefore impossible.
--
--   * FORCE applies the policies to the table owner too — which is the
--     admin that Alembic runs as. Any future data migration would then be
--     silently filtered to whichever tenant happened to be set, which is
--     a worse failure than the one FORCE prevents.
--
-- So RLS is ENABLEd and not FORCEd: the owner bypasses, and the owner is
-- the admin credential, which already has total access to this database
-- and is used only to migrate. The property FORCE would have bought —
-- that the application cannot read across tenants even by connecting as
-- a privileged role — is asserted at application startup instead, where
-- it can be tested: both apps refuse to start if their connection is
-- superuser, BYPASSRLS, or the owner of core.grants.
-- =====================================================================

-- One tenant per database was the previous invariant. It is now the thing
-- being removed, deliberately. The reasoning behind it is preserved in
-- 0004_tenant_singleton.sql rather than deleted, because a future reader
-- deciding whether to go back to a database per organization should find
-- the argument, not just the reversal.
DROP INDEX IF EXISTS core.tenants_singleton;


-- The tenant of the current session, or NULL when none is set.
--
-- NULL is the safe value: every policy below compares against it, and
-- `tenant_id = NULL` is NULL, so an unscoped session sees no rows rather
-- than every row. A malformed value raises instead — failing loudly beats
-- failing open. The application also refuses to issue queries with no
-- tenant set, so reaching this function with NULL means something has
-- already gone wrong.
CREATE FUNCTION core.current_tenant() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.tenant_id', true), '')::uuid
$$;


-- ---------------------------------------------------------------------
-- Tables that carry tenant_id: compare it directly.
--
-- WITH CHECK matches USING on every policy, so a session cannot write a
-- row into another organization's space either — reading and writing are
-- constrained by the same predicate.
-- ---------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'core.users', 'core.funders', 'core.metric_definitions',
        'core.documents', 'core.grants', 'core.obligations', 'core.audit_log',
        'perch.reporting_periods', 'perch.finance_facts',
        'perch.program_facts', 'perch.revenue_facts'
    ] LOOP
        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %s
                 USING (tenant_id = core.current_tenant())
                 WITH CHECK (tenant_id = core.current_tenant())', t);
    END LOOP;
END
$$;


-- core.tenants is scoped by its own primary key: a session may see the
-- organization it belongs to and no other. Without this, every tenant
-- could enumerate the client list.
ALTER TABLE core.tenants ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON core.tenants
    USING (id = core.current_tenant())
    WITH CHECK (id = core.current_tenant());


-- ---------------------------------------------------------------------
-- Child tables with no tenant_id of their own.
--
-- These were easy to overlook and carry some of the most sensitive rows
-- in the schema — budget lines, contacts, the provenance trail showing
-- what a human corrected. They are scoped through their parent.
--
-- The EXISTS subquery reads a table that is itself protected, so the
-- policies compose: the subquery can only see the current tenant's
-- parents, and therefore only matches the current tenant's children.
-- Denormalizing tenant_id onto each would be faster and is the usual
-- advice, but it introduces a second copy of the truth that can drift
-- from the parent, and drift here means a row visible to the wrong
-- organization.
-- ---------------------------------------------------------------------
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT * FROM (VALUES
        ('core.grant_field_provenance', 'grant_id',      'core.grants'),
        ('core.grant_contacts',         'grant_id',      'core.grants'),
        ('core.grant_budget_lines',     'grant_id',      'core.grants'),
        ('core.grant_workplan_tasks',   'grant_id',      'core.grants'),
        ('core.obligation_criteria',    'obligation_id', 'core.obligations'),
        ('perch.funder_field_aliases',  'metric_id',     'core.metric_definitions')
    ) AS v(child, fk, parent) LOOP
        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', r.child);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %s
                 USING (EXISTS (SELECT 1 FROM %s p WHERE p.id = %I))
                 WITH CHECK (EXISTS (SELECT 1 FROM %s p WHERE p.id = %I))',
            r.child, r.parent, r.fk, r.parent, r.fk);
    END LOOP;
END
$$;


-- ---------------------------------------------------------------------
-- Deliberately NOT protected.
--
-- core.funder_profiles is shared reference data — what a given funder
-- calls its metrics. It belongs to no organization and every tenant reads
-- the same rows. Named here so that "why is this table not in the list"
-- has an answer other than "it was missed".
--
-- core.alembic_version is migration bookkeeping with no tenant dimension,
-- and the app roles cannot read it at all.
-- ---------------------------------------------------------------------


-- ---------------------------------------------------------------------
-- The app roles must not be able to bypass any of the above.
--
-- BYPASSRLS is off by default, so this asserts rather than sets — and it
-- runs on every migration, so a role that acquires the attribute later
-- fails the next deploy instead of quietly reading every organization.
-- ---------------------------------------------------------------------
DO $$
DECLARE offender text;
BEGIN
    SELECT string_agg(rolname, ', ') INTO offender
      FROM pg_roles
     WHERE rolname IN ('gma_app', 'perch_app')
       AND (rolbypassrls OR rolsuper);
    IF offender IS NOT NULL THEN
        RAISE EXCEPTION
            'Role(s) % can bypass row-level security. With every '
            'organization in one database, that is unrestricted access to '
            'every nonprofit''s data. Revoke BYPASSRLS and SUPERUSER '
            'before applying this migration.', offender;
    END IF;
END
$$;
