-- =====================================================================
-- A fiscal year belongs to an organization, not to a deployment.
--
-- Perch read PERCH_FY_START_MONTH, one value per deployment. That was
-- correct when a deployment served one nonprofit and wrong the moment it
-- served several: organizations on a July-June year and a January-December
-- year cannot share it, and whichever one does not match gets every
-- year-to-date figure in every funder report computed over the wrong
-- window.
--
-- It fails silently, which is what makes it worth a migration rather than
-- a note. Nothing throws. A September report for a July-June organization
-- shows nine months of revenue as "year to date" when the answer is three.
-- The number is plausible, it goes to a funder, and nobody can tell by
-- looking.
--
-- Measured on the deployed system before this: ca-perch had no
-- PERCH_FY_START_MONTH set at all, so it defaulted to January, and the
-- DonorPerfect-derived year-to-date figures already in the database were
-- summed from 1 January regardless of what DuPage's year actually is. The
-- Excel GL figures were unaffected -- that connector reads ytd_actual
-- straight from the file rather than summing.
--
-- APPLYING THIS CHANGES NO FIGURE. The default is 1, which is exactly what
-- an unset PERCH_FY_START_MONTH meant, so every organization keeps the
-- behaviour it had until somebody sets its real value. That is deliberate:
-- a migration that silently restated last month's numbers would be worse
-- than the bug.
-- =====================================================================

ALTER TABLE core.tenants
    ADD COLUMN IF NOT EXISTS fiscal_year_start_month smallint NOT NULL DEFAULT 1;

-- A CHECK rather than validation in the application, because the figures
-- this feeds are the ones funders read. 13 is not a month and should not be
-- storable, whichever code path tries.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'tenants_fiscal_year_start_month_check'
           AND conrelid = 'core.tenants'::regclass
    ) THEN
        ALTER TABLE core.tenants
            ADD CONSTRAINT tenants_fiscal_year_start_month_check
            CHECK (fiscal_year_start_month BETWEEN 1 AND 12);
    END IF;
END
$$;

COMMENT ON COLUMN core.tenants.fiscal_year_start_month IS
    'Month this organization''s fiscal year begins: 1 = January, 7 = July. '
    'Perch computes year-to-date from it. Confirm it in writing with the '
    'organization''s finance lead before their first report -- getting it '
    'wrong misstates every YTD figure without raising anything.';

-- core.tenant_directory is deliberately NOT widened. It is the one
-- owner-scoped view, readable before a tenant is known, and it exists so
-- login can turn a slug into an id. It holds two columns because every
-- column added to it is disclosed to anyone who can reach the login
-- endpoint. The fiscal year is read separately, through the caller's own
-- scoped connection, after authentication.

-- ---------------------------------------------------------------------
-- Assert it, on every run.
-- ---------------------------------------------------------------------
DO $$
DECLARE
    col_nullable text;
    has_check boolean;
    directory_cols integer;
BEGIN
    SELECT is_nullable INTO col_nullable
      FROM information_schema.columns
     WHERE table_schema = 'core' AND table_name = 'tenants'
       AND column_name = 'fiscal_year_start_month';
    IF col_nullable IS NULL THEN
        RAISE EXCEPTION 'core.tenants.fiscal_year_start_month was not created';
    END IF;
    IF col_nullable <> 'NO' THEN
        RAISE EXCEPTION
            'core.tenants.fiscal_year_start_month is nullable. A NULL fiscal '
            'year has no safe interpretation: the application would have to '
            'guess, and the guess would be silent.';
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'tenants_fiscal_year_start_month_check'
           AND conrelid = 'core.tenants'::regclass
    ) INTO has_check;
    IF NOT has_check THEN
        RAISE EXCEPTION
            'the 1-12 CHECK on core.tenants.fiscal_year_start_month is '
            'missing, so a month of 0 or 13 is storable';
    END IF;

    SELECT count(*) INTO directory_cols
      FROM information_schema.columns
     WHERE table_schema = 'core' AND table_name = 'tenant_directory';
    IF directory_cols <> 2 THEN
        RAISE EXCEPTION
            'core.tenant_directory has % columns, expected 2 (id, slug). It '
            'is readable before any organization is known, so anything added '
            'to it is disclosed at the login endpoint.', directory_cols;
    END IF;
END
$$;
