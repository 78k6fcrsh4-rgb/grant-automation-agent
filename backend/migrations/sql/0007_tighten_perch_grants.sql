-- =====================================================================
-- GRANT ALL handed perch_app a cross-tenant destruction path.
--
-- Migration 0003 wrote `GRANT ALL ON ALL TABLES IN SCHEMA perch TO
-- perch_app`, which was shorthand for "Perch owns its own measurements".
-- ALL includes TRUNCATE, REFERENCES and TRIGGER.
--
-- Row-level security does not apply to TRUNCATE. Measured, with two
-- organizations' rows present:
--
--   as perch_app, scoped to DuPage:
--     TRUNCATE perch.program_facts ....... 2 rows before, 0 after
--     DELETE FROM perch.program_facts .... 2 rows before, 1 after (correct)
--
-- So any code path, injection or mistake reaching TRUNCATE erases every
-- organization's financial and program history in one statement, with the
-- policies fully in force and the session correctly scoped. DELETE, by
-- contrast, is constrained exactly as intended.
--
-- REFERENCES is a quieter problem: it permits creating a foreign key
-- against a table, and a foreign key can be used to test whether a value
-- exists in rows the policy hides.
--
-- The fix is to say what Perch actually does instead of ALL. It reads its
-- facts, writes new ones, and supersedes old ones by stamping
-- superseded_at. It has never deleted a row — the fact tables are
-- append-only by design, with deleted_at for the disposal path — so DELETE
-- is not granted either.
-- =====================================================================

REVOKE ALL ON ALL TABLES IN SCHEMA perch FROM perch_app;

-- The fact tables and their period: read, append, supersede.
GRANT SELECT, INSERT, UPDATE ON
    perch.reporting_periods,
    perch.finance_facts,
    perch.program_facts,
    perch.revenue_facts,
    perch.funder_field_aliases
TO perch_app;

-- The views are read-only by nature; saying so explicitly costs nothing.
GRANT SELECT ON
    perch.v_current_finance,
    perch.v_current_program,
    perch.v_current_revenue,
    perch.v_program_for_export
TO perch_app;

-- gma_app stays revoked from the whole schema, as 0003 established: the
-- service holding the OpenAI credential cannot read a donor label or a
-- program outcome.
REVOKE ALL ON SCHEMA perch FROM gma_app;
REVOKE ALL ON ALL TABLES IN SCHEMA perch FROM gma_app;


-- ---------------------------------------------------------------------
-- Assert it, on every run. TRUNCATE is invisible to row-level security,
-- so a future GRANT ALL would silently restore a one-statement path to
-- erasing every organization's data.
-- ---------------------------------------------------------------------
DO $$
DECLARE offender text;
BEGIN
    SELECT string_agg(DISTINCT grantee || ' has ' || privilege_type ||
                      ' on ' || table_schema || '.' || table_name, '; ')
      INTO offender
      FROM information_schema.role_table_grants
     WHERE grantee IN ('gma_app', 'perch_app')
       AND table_schema IN ('core', 'perch')
       AND privilege_type IN ('TRUNCATE', 'REFERENCES', 'TRIGGER');
    IF offender IS NOT NULL THEN
        RAISE EXCEPTION
            'Application roles hold privileges that row-level security does '
            'not constrain: %. TRUNCATE ignores policies entirely and erases '
            'every organization''s rows; REFERENCES can be used to test for '
            'the existence of rows the policy hides. Grant SELECT, INSERT '
            'and UPDATE explicitly rather than ALL.', offender;
    END IF;
END
$$;
