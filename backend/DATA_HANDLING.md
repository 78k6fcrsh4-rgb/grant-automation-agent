# Data handling — forget by design

This app is a tool to help an organization **manage a grant when it is awarded**.
It deliberately does **not** retain grant documents.

From v2.8.0 it runs in one of two modes, and **which one is in force is shown to
the user on the review page and reported by `/health`** — nobody should be under
a data-retention contract they cannot see.

| `GMA_PERSISTENCE` | What happens |
|---|---|
| `ephemeral` (default) | Standalone. Nothing below the "User accounts" row is ever written to a database. This is the original behaviour, unchanged. |
| `linked` | Connected to Perch. Everything below still applies to the working copy; in addition, **the confirmed record** — funder, amount, period, obligations, budget lines, work plan, provenance — is filed to `core.grants` as the organization's record of the award. |

**In both modes the document itself is forgotten.** `raw_text`, `proposal_text`,
`award_letter_text`, `redacted_text`, the transmission preview and the uploaded
file never reach a database. This is enforced, not documented: the whitelist in
`app/services/grant_persistence.py` raises if a document-derived value would be
written, `core.documents` has no column that could hold text, and
`PATCH /api/grants/data/{id}` rejects unknown fields so a client cannot patch
document text onto a grant either.

The document is forgotten; the commitment is remembered.

## What is kept, and for how long

| Data | Where | Lifetime |
|------|-------|----------|
| User accounts (email + bcrypt hash) | Database | Persistent (needed for login) |
| Uploaded source documents (proposal, award letter) | temp dir | **Deleted immediately after text extraction** |
| Extracted grant data | In memory only | Purged after `GRANT_TTL_MINUTES` idle (default 120), and on restart |
| Generated documents (xlsx/docx/pdf/ics) | temp dir | Deleted when the grant is purged; whole dir wiped on startup |

In `ephemeral` mode grant data is **never written to a durable database**: there
is no long-term store of grantee PII to protect, breach, audit, or honor deletion
requests against.

In `linked` mode the confirmed award terms are retained — that is the point of
linking — and are covered by the shared audit log (`core.audit_log`, append-only)
and the deletion path on `core.grants`. The uploaded documents are still not
retained in either mode.

## How "forget" is enforced
- Source files are removed from disk the moment their text is extracted.
- Each grant carries an idle timestamp; a background sweeper
  (`PURGE_INTERVAL_SECONDS`, default 300) forgets anything idle past the TTL.
- Accessing a grant slides its clock, so active sessions are never purged mid-use.
- `DELETE /api/grants/{id}` is an explicit "forget now" for the working copy. In
  linked mode it does **not** retract a grant already filed to `core` — closing a
  session is not withdrawing an award. Deleting a filed grant is a separate,
  audited action.
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

**Concurrency within the replica:** the upload and document-generation endpoints run synchronously in FastAPI's worker threadpool, so a slow extraction (LLM call or OCR) runs in its own thread and does not block other users' requests. One instance can therefore serve many concurrent users; the ceiling is the container's CPU/RAM and OpenAI rate limits. True horizontal scale (multiple replicas) still requires the shared-store step below.

For the current scale (a handful of organizations, short single-session
workflows) a single replica is more than sufficient and keeps the model simple.
If you later need true horizontal scale, the drop-in upgrade is a shared cache
with the same TTL (e.g. Redis) — same forget-by-design behavior, coherent across
replicas — with no change to the API.
