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
- `DATABASE_URL` — defaults to local SQLite (`sqlite:///./data/app.db`).
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

## IMPORTANT for Azure Container Apps: durable storage
The container filesystem is **ephemeral** — a plain SQLite file at `./data`
would be wiped on every deploy, erasing all users. Choose one:

1. **Azure Files volume (keep SQLite):** create a storage share, add it to the
   Container Apps environment, and mount it at `/app/data` on `ca-grants-backend`.
   `DATABASE_URL=sqlite:////app/data/app.db`. Simplest, fully portable code.
2. **Managed Postgres (recommended for multi-user):** provision Azure Database
   for PostgreSQL and set
   `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/grants`.
   Add `psycopg[binary]` to requirements.

Set `SECRET_KEY` as a Container App secret (same pattern as the OpenAI key —
Key Vault reference is ideal).

## Note: grants are still in-memory
User accounts are now durable, but **grant data is still stored in memory** and
resets on deploy. Persisting grants per-tenant in the database is the natural
next step (and pairs with the multi-replica fix noted in the original review).
