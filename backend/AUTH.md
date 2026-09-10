# Authentication & multi-tenancy

Portable, app-level login. No external identity provider, so it moves to any
host (current Azure → United Way) with zero changes — only environment vars.

## How it works
- **Login:** `POST /api/auth/login` with `{email, password}` → returns a JWT
  (`access_token`) plus the user record. The frontend stores the token and
  sends it as `Authorization: Bearer <token>` on every request.
- **Passwords:** hashed with bcrypt. Never stored or logged in plaintext.
- **Sessions:** stateless JWT signed with `SECRET_KEY`, expiring after
  `ACCESS_TOKEN_EXPIRE_MINUTES` (default 8h).
- **Tenancy:** every user belongs to a `Tenant`. Grants are scoped by tenant,
  so one organization never sees another's data. Today there's one tenant
  (DuPage Health Coalition); adding more later is just new rows — no schema change.
- **Roles:** `admin` can create users in their tenant (`POST /api/auth/users`);
  `member` cannot.

## Required configuration
Set these in the backend environment (see `.env.example`):
- `SECRET_KEY` — long random string. Generate:
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- `DATABASE_URL` — **required**, PostgreSQL. From v2.8.0 SQLite is rejected at
  startup: identity lives in the shared `core` schema, which uses citext, enums
  and partial unique indexes. One database per partner organization:
  `postgresql+psycopg://gma_app:pass@host:5432/gma_dupage`.
- `AUTO_MIGRATE` — optional, default `true`. Runs `alembic upgrade head` on boot.
- `ACCESS_TOKEN_EXPIRE_MINUTES` — optional, default 480.

## First-time seed (create DuPage + its admin)
```bash
cd backend
python -m scripts.seed_admin \
  --tenant "DuPage Health Coalition" --slug dupage \
  --email admin@dupagehealth.org --password 'A-STRONG-PASSWORD' --name "Admin Name"
```
Then that admin can add staff accounts via `POST /api/auth/users` (or a future
UI screen).

## Azure Container Apps: durable storage
The container filesystem is **ephemeral**, which is why the old SQLite default
never actually survived a deploy. v2.8.0 settles it: provision Azure Database for
PostgreSQL Flexible Server and set
`DATABASE_URL=postgresql+psycopg://user:pass@host:5432/gma_<org>`.
`psycopg[binary]` and `alembic` are in requirements.txt.

One **database** per partner organization on one shared **server**: Postgres
cannot join across databases without an explicit FDW, so a missed tenant filter
fails closed rather than returning another organization's records. Migrations run
once per database, so keep them idempotent and never hand-apply SQL.

## Roles
`admin` and `user`. The pre-2.8.0 spelling was `admin`/`member`; the migration
rewrites existing rows, and `SEED_USERS` entries that still say `"member"` are
accepted and normalised so an already-deployed pilot login is not broken by a
word change.

Set `SECRET_KEY` as a Container App secret (same pattern as the OpenAI key —
Key Vault reference is ideal).

## Note: grant data is intentionally ephemeral
User accounts are durable (needed for login), but **grant data is deliberately
transient** — held in memory, auto-purged after an idle window, never written to
a database. This is by design; see DATA_HANDLING.md. Run the backend as a single
replica (or with session affinity) so a session's follow-up requests reach the
same process.
