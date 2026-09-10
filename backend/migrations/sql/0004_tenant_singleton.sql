-- =====================================================================
-- One tenant per database, enforced rather than assumed.
--
-- Isolation between organizations is the database boundary: one database
-- per org on a shared server, so Postgres cannot join across them without
-- an explicit FDW and a missed filter fails closed. That guarantee holds
-- only while each database really does contain one organization.
--
-- Until now that was a convention. Several code paths quietly depend on
-- it — pg_storage._tenant_id() resolves the org with ORDER BY created_at
-- LIMIT 1, which under two tenant rows would not error, it would silently
-- attribute Perch's writes to whichever tenant was seeded first.
--
-- A unique index on a constant expression permits exactly one row. A
-- provisioning script pointed at the wrong organization's database, or a
-- seed run twice with different values, now fails loudly on insert
-- instead of creating a second org inside a database not built to hold
-- one.
--
-- Written out in grant-platform/schema.sql, commented, as the thing to
-- turn on before there is ever a second organization. This turns it on.
-- =====================================================================

-- Fail with something a human can act on, rather than a bare duplicate
-- key error from the index creation below.
DO $$
DECLARE
    n integer;
BEGIN
    SELECT count(*) INTO n FROM core.tenants;
    IF n > 1 THEN
        RAISE EXCEPTION
            'core.tenants holds % rows; this database is meant to hold one '
            'organization. Resolve which tenant belongs here (and move the '
            'other to its own database) before applying this migration.', n;
    END IF;
END
$$;

CREATE UNIQUE INDEX tenants_singleton ON core.tenants ((true));
