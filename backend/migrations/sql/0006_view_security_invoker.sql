-- =====================================================================
-- Views were bypassing row-level security completely.
--
-- A Postgres view executes with the privileges of its OWNER unless
-- security_invoker is set. Every view here is owned by the admin, and the
-- admin bypasses the policies (migration 0005 explains why FORCE is not
-- available). So each view returned every organization's rows to any role
-- allowed to read the view, no matter what tenant the session was scoped
-- to — or whether it was scoped at all.
--
-- Measured, as perch_app, with two organizations present:
--
--   base table core.obligations, scoped to DuPage ...... 1 row  (correct)
--   view core.v_upcoming_obligations, same session ..... 2 rows (DuPage AND
--                                                        Deborah's Place)
--   view core.v_upcoming_obligations, no tenant set .... 2 rows
--
-- v_upcoming_obligations is what Perch's deadline tracker reads. Every
-- organization would have seen every other organization's reporting
-- deadlines, funders and grant titles, on the main screen of the app.
--
-- 0005 enabled RLS on the tables and stopped there. The tables were the
-- visible half of the problem.
-- =====================================================================

ALTER VIEW core.v_upcoming_obligations  SET (security_invoker = true);
ALTER VIEW core.v_extraction_overrides  SET (security_invoker = true);
ALTER VIEW perch.v_current_finance      SET (security_invoker = true);
ALTER VIEW perch.v_current_program      SET (security_invoker = true);
ALTER VIEW perch.v_current_revenue      SET (security_invoker = true);
ALTER VIEW perch.v_program_for_export   SET (security_invoker = true);


-- ---------------------------------------------------------------------
-- The one view that is deliberately NOT invoker-scoped.
--
-- Authentication has a bootstrapping problem: a session cannot be scoped
-- to an organization until we know which one the person belongs to, and
-- under RLS an unscoped lookup of core.users returns nothing. So nobody
-- could log in.
--
-- The obvious fix — a SECURITY DEFINER function returning a user row for a
-- given email — was rejected. It would hand back any user's password hash
-- to anyone who could call it, and it would exist solely to work around
-- the isolation this migration series is building.
--
-- Instead the person names their organization at login, and the only
-- globally readable thing is the mapping from slug to id. Owner-scoped on
-- purpose, so it can be read before a tenant is known; two columns wide,
-- so it can disclose nothing but the fact that an organization exists and
-- what it is called — which is already on the login page they typed it
-- into. No user rows, no password hashes, no grant data.
--
-- The user lookup then happens INSIDE the tenant scope, like every other
-- query, with no exception needed.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW core.tenant_directory AS
    SELECT id, slug FROM core.tenants;

GRANT SELECT ON core.tenant_directory TO gma_app, perch_app;


-- ---------------------------------------------------------------------
-- Assert the rule, on every run: any view in core or perch that is not
-- the directory must be invoker-scoped. A view added later without it is
-- a silent hole of exactly the kind this migration is closing, and the
-- next deploy should fail rather than ship it.
-- ---------------------------------------------------------------------
DO $$
DECLARE offender text;
BEGIN
    SELECT string_agg(n.nspname || '.' || c.relname, ', ')
      INTO offender
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.relkind = 'v'
       AND n.nspname IN ('core', 'perch')
       AND n.nspname || '.' || c.relname <> 'core.tenant_directory'
       AND NOT EXISTS (
             SELECT 1 FROM unnest(coalesce(c.reloptions, '{}')) opt
              WHERE opt = 'security_invoker=true');
    IF offender IS NOT NULL THEN
        RAISE EXCEPTION
            'View(s) % run with their owner''s privileges, which bypasses '
            'row-level security entirely — every organization''s rows are '
            'returned to anyone who can read the view. Add '
            'WITH (security_invoker = true).', offender;
    END IF;
END
$$;
