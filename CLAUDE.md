# Project notes for Claude

## Versioning policy
- The app version lives in FOUR places that must stay in sync:
  `frontend/package.json`, `backend/app/__init__.py` (`__version__`),
  `backend/app/main.py` (FastAPI `version=` and the root endpoint response),
  and `frontend/package-lock.json` (root `version` + `packages[""].version`).
- After ANY frontend version bump, run `cd frontend && npm install` so
  package-lock.json stays in sync. The frontend Docker build runs `npm ci`,
  which FAILS the deploy if the lockfile is out of sync with package.json.
- On any major/feature-level push, PROPOSE a version bump and ASK Parker to
  confirm the number before committing (e.g. "this looks like 2.6.0 — agree?").
  Patch-level fixes may bump the patch number without asking.
- Current version: 2.8.0 (Phase 1 of the Perch integration: shared `core`
  schema on PostgreSQL, Alembic migrations, editable review + confirm,
  and the ephemeral/linked persistence split).

## Deploy facts
- Deploys trigger ONLY on push to `main` (.github/workflows/deploy.yml).
- Docker builds use --no-cache: expect ~8–12 min per deploy + ~2 min revision rollout.
- OPENAI_API_KEY reaches the backend via Key Vault reference + system-assigned
  managed identity (one-time setup: infra/setup-keyvault-identity.sh). CI never
  handles the secret value.

## Testing
- Offline suite: `cd backend && python -m pytest` (no API key needed). Tests that
  need a database skip cleanly when `TEST_DATABASE_URL` is unset.
- Full suite: `TEST_DATABASE_URL=postgresql+psycopg://... python -m pytest`.
  The URL must point at a THROWAWAY database — `core` is dropped and recreated.
- Golden-set live test: `OPENAI_API_KEY=... python -m pytest -m integration`
  asserts the Milton/DuPage FY2026 values ($33,600, DuPage Health Coalition, etc.).

## Database (v2.8.0+)
- PostgreSQL only. SQLite is rejected at startup: the shared `core` schema uses
  citext, enums, partial unique indexes and generated columns.
- One database per partner organization, all on one shared server. Isolation is
  the database boundary, not an application check.
- Alembic owns the schema; nothing calls `create_all`. Migrations run once per
  organization's database, so they must stay idempotent.
- `AUTO_MIGRATE=true` (default) makes the app run `alembic upgrade head` on boot.
- The executable schema is `backend/migrations/sql/0001_core.sql`; its design
  reference is `grant-platform/schema.sql` in WorkBench. Keep them in step.
- `GMA_PERSISTENCE=ephemeral|linked` decides whether a confirmed grant is filed
  to `core.grants`. See backend/DATA_HANDLING.md.
