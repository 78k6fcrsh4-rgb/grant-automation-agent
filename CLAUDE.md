# Project notes for Claude

## Versioning policy
- The app version lives in THREE places that must stay in sync:
  `frontend/package.json`, `backend/app/__init__.py` (`__version__`), and
  `backend/app/main.py` (FastAPI `version=` and the root endpoint response).
- On any major/feature-level push, PROPOSE a version bump and ASK Parker to
  confirm the number before committing (e.g. "this looks like 2.6.0 — agree?").
  Patch-level fixes may bump the patch number without asking.
- Current version: 2.5.0 (LLM-first extraction rewrite + Key Vault managed identity).

## Deploy facts
- Deploys trigger ONLY on push to `main` (.github/workflows/deploy.yml).
- Docker builds use --no-cache: expect ~8–12 min per deploy + ~2 min revision rollout.
- OPENAI_API_KEY reaches the backend via Key Vault reference + system-assigned
  managed identity (one-time setup: infra/setup-keyvault-identity.sh). CI never
  handles the secret value.

## Testing
- Offline suite: `cd backend && python -m pytest` (no API key needed).
- Golden-set live test: `OPENAI_API_KEY=... python -m pytest -m integration`
  asserts the Milton/DuPage FY2026 values ($33,600, DuPage Health Coalition, etc.).
