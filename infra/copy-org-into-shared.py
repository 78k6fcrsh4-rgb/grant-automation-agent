#!/usr/bin/env python3
"""Copy one organization's data from its own database into the shared one.

    python3 infra/copy-org-into-shared.py --source gma_dupage --target gma_platform

WHAT THIS IS FOR

Until now each organization had a database to itself, which was the isolation
boundary. The shared database separates them by row-level security instead, so
the rows have to move. This moves them.

It is deliberately a one-way, one-organization-at-a-time operation that
verifies everything it can before and after, because losing or duplicating a
nonprofit's grant history is not a recoverable mistake.

WHY IT NEEDS NO TENANT FILTER

Migration 0004 enforced one tenant per database with a unique index on a
constant expression. So every row in the source belongs to the organization
being moved, and the copy needs no predicate — which also means it cannot get
one subtly wrong. The script verifies that single-tenant assumption first and
refuses if the source holds more than one.

WHY THE TABLE LIST IS NOT WRITTEN DOWN

It is read from the catalogue and sorted by foreign-key dependency. A list in
a file goes stale the first time a migration adds a table, and the failure is
silent: the new table simply is not copied. Writing this, a hand-made list of
"the eleven tables with a tenant_id" turned out to miss five that hold real
data — grant_budget_lines, grant_contacts, grant_field_provenance,
grant_workplan_tasks and obligation_criteria reach their tenant through a
parent rather than carrying the column.

WHAT IT CHECKS

Before:  source has exactly one tenant; that tenant exists in the target with
         the SAME id; every table's columns match between the two; the target
         has no rows for this tenant yet.
After:   every table's row count in the target equals the source's, and the
         audit_log sequence is past the highest id copied.

Run with --dry-run first. It prints exactly what it would copy and changes
nothing.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

SCHEMAS = ("core", "perch")
SKIP = {"core.alembic_version", "perch.alembic_version"}

# core.tenants is inserted by hand before this runs, with the id preserved —
# that is what makes the copy a copy rather than a rewrite. Copying it here
# would collide on the row that makes the rest possible.
SKIP_COPY = {"core.tenants"}


def connect(url: str):
    import psycopg

    return psycopg.connect(url, autocommit=False)


def tables(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT n.nspname || '.' || c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind = 'r' AND n.nspname = ANY(%s)
            """,
            (list(SCHEMAS),),
        )
        return sorted(r[0] for r in cur.fetchall() if r[0] not in SKIP)


def columns(conn, table: str) -> list[str]:
    schema, name = table.split(".", 1)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.attname
              FROM pg_attribute a
              JOIN pg_class c ON c.oid = a.attrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = %s AND c.relname = %s
               AND a.attnum > 0 AND NOT a.attisdropped
               AND a.attgenerated = ''
             ORDER BY a.attnum
            """,
            (schema, name),
        )
        return [r[0] for r in cur.fetchall()]


def dependencies(conn, known: set[str]) -> dict[str, set[str]]:
    """table -> the tables it references, self-references excluded.

    A self-reference (perch fact tables point at their own superseded_by) is
    not an ordering constraint, and the deferred self-FK resolves inside the
    transaction.
    """
    deps: dict[str, set[str]] = defaultdict(set)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT      sn.nspname || '.' || s.relname AS child,
                        tn.nspname || '.' || t.relname AS parent
              FROM pg_constraint con
              JOIN pg_class s ON s.oid = con.conrelid
              JOIN pg_namespace sn ON sn.oid = s.relnamespace
              JOIN pg_class t ON t.oid = con.confrelid
              JOIN pg_namespace tn ON tn.oid = t.relnamespace
             WHERE con.contype = 'f'
            """
        )
        for child, parent in cur.fetchall():
            if child in known and parent in known and child != parent:
                deps[child].add(parent)
    return deps


def copy_order(table_list: list[str], deps: dict[str, set[str]]) -> list[str]:
    """Parents before children. Raises on a cycle rather than guessing."""
    ordered: list[str] = []
    remaining = set(table_list)
    while remaining:
        ready = sorted(t for t in remaining if not (deps.get(t, set()) & remaining))
        if not ready:
            raise SystemExit(
                "error: foreign keys among these tables form a cycle, so there "
                "is no safe copy order: " + ", ".join(sorted(remaining))
            )
        ordered.extend(ready)
        remaining -= set(ready)
    return ordered


def count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


def one_value(conn, sql: str):
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-url", required=True,
                    help="admin URL for the organization's own database")
    ap.add_argument("--target-url", required=True,
                    help="admin URL for the shared database")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be copied and change nothing")
    args = ap.parse_args()

    src = connect(args.source_url)
    dst = connect(args.target_url)

    # ---------------------------------------------------------- before
    src_tenants = one_value(src, "SELECT count(*) FROM core.tenants")
    if src_tenants != 1:
        sys.exit(
            f"error: the source holds {src_tenants} organizations, not 1.\n"
            f"       This copies a whole database on the assumption that every "
            f"row in it belongs to one organization, which migration 0004 "
            f"enforced. With more than one, every table would need a tenant "
            f"predicate and this is the wrong tool."
        )

    tenant_id, slug, name = None, None, None
    with src.cursor() as cur:
        cur.execute("SELECT id, slug, name FROM core.tenants")
        tenant_id, slug, name = cur.fetchone()

    target_id = one_value(dst, f"SELECT id FROM core.tenants WHERE slug = '{slug}'")
    if target_id is None:
        sys.exit(
            f"error: the target has no organization with slug {slug!r}.\n"
            f"       Insert it FIRST, preserving the id, so this is a copy "
            f"rather than a rewrite:\n"
            f"         INSERT INTO core.tenants (id, name, slug)\n"
            f"         VALUES ('{tenant_id}', '{name}', '{slug}');"
        )
    if str(target_id) != str(tenant_id):
        sys.exit(
            f"error: {slug!r} has a different id in each database.\n"
            f"       source {tenant_id}\n"
            f"       target {target_id}\n"
            f"       Every tenant_id in the copied rows would point at the "
            f"wrong organization, and the foreign keys would accept it. Delete "
            f"the target's row and re-insert it with the source's id."
        )

    print(f"==> {name} ({slug})")
    print(f"    tenant id {tenant_id}, the same in both databases")

    src_tables = tables(src)
    dst_tables = tables(dst)
    missing = sorted(set(src_tables) - set(dst_tables))
    if missing:
        sys.exit("error: the target is missing tables the source has: "
                 + ", ".join(missing) + "\n       Migrate the target to head.")

    for table in src_tables:
        a, b = columns(src, table), columns(dst, table)
        if a != b:
            sys.exit(
                f"error: {table} has different columns in each database.\n"
                f"       source {a}\n"
                f"       target {b}\n"
                f"       Both must be migrated to the same revision."
            )

    to_copy = [t for t in src_tables if t not in SKIP_COPY]
    order = copy_order(to_copy, dependencies(src, set(to_copy)))

    src_counts = {t: count(src, t) for t in order}
    nonempty = [t for t in order if src_counts[t]]

    # Refuse to add to a tenant that already has rows here. Running this twice
    # would double every figure, and nothing downstream would notice.
    already = []
    for table in nonempty:
        if "tenant_id" in columns(dst, table):
            n = one_value(dst, f"SELECT count(*) FROM {table} "
                               f"WHERE tenant_id = '{tenant_id}'")
            if n:
                already.append(f"{table} ({n} rows)")
    if already:
        sys.exit(
            "error: the target already holds rows for this organization:\n"
            + "".join(f"         {x}\n" for x in already)
            + "       Copying again would double them. Remove them first, or "
              "if this already ran, there is nothing to do."
        )

    print(f"    {len(nonempty)} of {len(order)} tables hold rows")
    for table in order:
        marker = " " if src_counts[table] else "-"
        print(f"      {marker} {table:<34} {src_counts[table]:>7}")

    if args.dry_run:
        print("\n    --dry-run: nothing was copied.")
        return 0

    # ---------------------------------------------------------- copy
    #
    # Each table goes through an unlogged staging table and then an INSERT ...
    # ON CONFLICT DO NOTHING, rather than COPYing straight into place.
    #
    # The reason is core.funder_profiles and perch.funder_field_aliases. They
    # carry no tenant_id because they are shared lookups, they are populated by
    # the application rather than by a migration, and so they exist in the
    # source and may or may not already exist in the target. A direct COPY
    # collides on the primary key and takes the whole transaction down with it;
    # with staging, the rows that are already there are skipped and the rest
    # land. Two of the primary keys are composite, which is the other reason
    # not to hand-roll the exclusion.
    #
    # Skipping is only ever expected on those shared lookups. For anything
    # carrying a tenant_id, a skipped row would mean a collision with another
    # organization's data, so the check after this insists the counts match
    # exactly and names the table if they do not.
    print("\n==> Copying")
    no_tenant = {t for t in nonempty if "tenant_id" not in columns(dst, t)}
    skipped: dict[str, int] = {}
    try:
        for table in nonempty:
            cols = ", ".join(f'"{c}"' for c in columns(src, table))
            stage = "_stage_" + table.replace(".", "_")
            with dst.cursor() as cur:
                cur.execute(f"CREATE TEMP TABLE {stage} "
                            f"(LIKE {table}) ON COMMIT DROP")
            with src.cursor().copy(
                f"COPY (SELECT {cols} FROM {table}) TO STDOUT"
            ) as out, dst.cursor().copy(
                f"COPY {stage} ({cols}) FROM STDIN"
            ) as into:
                for block in out:
                    into.write(block)
            with dst.cursor() as cur:
                cur.execute(f"INSERT INTO {table} ({cols}) "
                            f"SELECT {cols} FROM {stage} "
                            f"ON CONFLICT DO NOTHING")
                inserted = cur.rowcount
                cur.execute(f"SELECT count(*) FROM {stage}")
                staged = cur.fetchone()[0]
            if staged != inserted:
                skipped[table] = staged - inserted
            note = "" if staged == inserted else f"   ({staged - inserted} already present)"
            print(f"      {table:<34} {inserted:>7}{note}")

        unexpected = {t: n for t, n in skipped.items() if t not in no_tenant}
        if unexpected:
            raise SystemExit(
                "error: rows were skipped in tables that carry a tenant_id:\n"
                + "".join(f"         {t}: {n} rows\n"
                          for t, n in sorted(unexpected.items()))
                + "       A conflict there means a primary key collides with "
                  "another organization's row, which should be impossible. "
                  "Nothing was committed."
            )

        # The sequence does not travel with the rows it numbered.
        high = one_value(dst, "SELECT coalesce(max(id), 0) FROM core.audit_log")
        with dst.cursor() as cur:
            cur.execute("SELECT setval('core.audit_log_id_seq', %s)",
                        (max(int(high), 1),))
        print(f"      core.audit_log_id_seq set to {max(int(high), 1)}")

        # ------------------------------------------------------ after
        bad = []
        for table in nonempty:
            if count(dst, table) != src_counts[table]:
                bad.append(f"{table}: source {src_counts[table]}, "
                           f"target {count(dst, table)}")
        if bad:
            raise SystemExit("error: row counts do not match after copying:\n"
                             + "".join(f"         {x}\n" for x in bad))

        dst.commit()
        print("\n==> Committed. Row counts match in every table.")
    except Exception:
        dst.rollback()
        print("\n==> Rolled back. The target is unchanged.", file=sys.stderr)
        raise
    finally:
        src.close()
        dst.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
