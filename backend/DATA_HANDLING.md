# Data handling — forget by design

This app is a tool to help an organization **manage a grant when it is awarded**,
not a system of record. It deliberately does **not** retain grant documents or
extracted data.

## What is kept, and for how long

| Data | Where | Lifetime |
|------|-------|----------|
| User accounts (email + bcrypt hash) | Database | Persistent (needed for login) |
| Uploaded source documents (proposal, award letter) | temp dir | **Deleted immediately after text extraction** |
| Extracted grant data | In memory only | Purged after `GRANT_TTL_MINUTES` idle (default 120), and on restart |
| Generated documents (xlsx/docx/pdf/ics) | temp dir | Deleted when the grant is purged; whole dir wiped on startup |

Grant data is **never written to a durable database**. There is no long-term
store of grantee PII to protect, breach, audit, or honor deletion requests
against — the strongest posture for handling sensitive third-party data.

## How "forget" is enforced
- Source files are removed from disk the moment their text is extracted.
- Each grant carries an idle timestamp; a background sweeper
  (`PURGE_INTERVAL_SECONDS`, default 300) forgets anything idle past the TTL.
- Accessing a grant slides its clock, so active sessions are never purged mid-use.
- `DELETE /api/grants/{id}` is an explicit "forget now."
- On startup the temp dir is wiped of any files orphaned by a previous run.

## Operational requirement: run a single replica (or use session affinity)
Because grant data lives in the memory of the process that received the upload,
a later request (generate/download) must reach that **same** process. Configure
the backend Container App accordingly:

```bash
# Simplest: pin to one replica.
az containerapp update -n ca-grants-backend -g rg-grantsops \
  --min-replicas 1 --max-replicas 1

# Or allow scale-out but keep a user pinned to one replica:
az containerapp ingress sticky-sessions set -n ca-grants-backend -g rg-grantsops \
  --affinity sticky
```

For the current scale (a handful of organizations, short single-session
workflows) a single replica is more than sufficient and keeps the model simple.
If you later need true horizontal scale, the drop-in upgrade is a shared cache
with the same TTL (e.g. Redis) — same forget-by-design behavior, coherent across
replicas — with no change to the API.
