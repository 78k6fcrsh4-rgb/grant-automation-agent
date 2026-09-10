"""Mapping the in-memory GrantData onto the shared `core` tables.

The whole file exists to make one boundary explicit and testable: what
crosses from an extraction session into the database, and what never
does.

NEVER_PERSIST is not a convention — `assert_no_document_text()` is called
on every write path and raises if any of those fields would travel. The
document is forgotten; the commitment is remembered.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import core_models as cm
from app.models.schemas import GrantData

# Document text and anything derived from it verbatim. These stay in the
# ephemeral store for the life of the session and are never written.
NEVER_PERSIST = frozenset({
    "raw_text",
    "proposal_text",
    "award_letter_text",
    "redacted_text",
    "transmission_preview",   # carries a 1200-char excerpt of the document
    "local_extraction_summary",
    "redactions",             # each entry holds a preview of the original span
})

# The six scalars that carry provenance and can be corrected on review.
PERSISTED_SCALARS = (
    "organization_name", "funder_name", "grant_title",
    "purpose", "grant_amount", "grant_period",
)

_DATE_FORMATS = ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%m/%d/%Y", "%m-%d-%Y", "%d %B %Y")
_RANGE_SPLIT = re.compile(r"\s*(?:–|—|-|\bto\b|\bthrough\b)\s*", re.IGNORECASE)

# Timeline categories that become obligations, and the kind each maps to.
_TIMELINE_KIND = {
    "report": "report",
    "reimbursement": "disbursement",
    "disbursement": "disbursement",
    "payment": "disbursement",
    "submission": "submission",
    "deliverable": "deliverable",
    "milestone": "milestone",
    "meeting": "meeting",
    "deadline": "submission",
}


class DocumentTextLeak(RuntimeError):
    """Raised when a write path would carry document text into the database."""


# Below this length a "document" value is too short to distinguish from a
# legitimate field, and matching on it would produce false positives.
_LEAK_MIN_CHARS = 40
_LEAK_PROBE_CHARS = 120


def assert_no_document_text(payload: dict[str, Any]) -> None:
    """Guard for any dict-shaped payload headed for the database."""
    leaked = sorted(NEVER_PERSIST & {k for k, v in payload.items()
                                     if v not in (None, [], {}, "")})
    if leaked:
        raise DocumentTextLeak(
            "Refusing to persist document-derived fields: " + ", ".join(leaked))


def _document_values(grant_data: GrantData) -> list[tuple[str, str]]:
    """The document-derived strings that must never reach the database."""
    found: list[tuple[str, str]] = []
    for field in NEVER_PERSIST:
        value = getattr(grant_data, field, None)
        if field == "transmission_preview" and value is not None:
            value = getattr(value, "payload_excerpt", None)
        if isinstance(value, str) and len(value.strip()) >= _LEAK_MIN_CHARS:
            found.append((field, value.strip()))
    return found


def assert_no_leak(grant_data: GrantData, written: Iterable[Any]) -> None:
    """Verify that nothing about to be written carries document text.

    The explicit field mapping in persist_grant is what keeps document
    text out; this is the check that catches the day someone adds one
    more line to that mapping without thinking about it.
    """
    haystack = "\n".join(str(w) for w in written if isinstance(w, str))
    if not haystack:
        return
    for field, value in _document_values(grant_data):
        probe = value[:_LEAK_PROBE_CHARS]
        if probe and probe in haystack:
            raise DocumentTextLeak(
                f"Refusing to persist: a value derived from {field} would be "
                f"written to core. Document text never leaves the working store.")


def parse_date(value: Any) -> Optional[date]:
    """Free-text extraction date -> a real date, or None if it is not one.

    Returning None rather than guessing is deliberate: an obligation with
    an unparseable date is surfaced for a human to fix on the review page,
    which is where a date should be settled anyway.
    """
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value or not isinstance(value, str):
        return None
    text = value.strip().strip(".,;")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_period(raw: Any) -> tuple[Optional[date], Optional[date]]:
    """'July 1, 2026 - June 30, 2027' -> (date, date). Best effort, no guessing."""
    if not raw or not isinstance(raw, str):
        return (None, None)
    parts = [p for p in _RANGE_SPLIT.split(raw.strip()) if p]
    if len(parts) >= 2:
        return (parse_date(parts[0]), parse_date(parts[-1]))
    return (parse_date(raw), None)


def to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _confidence(grant_data: GrantData, field: str) -> str:
    raw = (grant_data.extraction_confidence or {}).get(field)
    value = getattr(raw, "value", raw)
    return value if value in ("confirmed", "inferred", "missing") else "missing"


def _scalar(grant_data: GrantData, field: str) -> Optional[str]:
    value = getattr(grant_data, field, None)
    return None if value is None else str(value)


def audit(db: Session, *, tenant_id: UUID, actor_user_id: Optional[UUID], action: str,
          table: str, entity_id: Optional[UUID] = None, field: Optional[str] = None,
          old_value: Any = None, new_value: Any = None,
          source_document_id: Optional[UUID] = None) -> None:
    db.add(cm.AuditLog(
        tenant_id=tenant_id, actor_user_id=actor_user_id, action=action,
        entity_schema="core", entity_table=table, entity_id=entity_id, field=field,
        old_value=None if old_value is None else str(old_value),
        new_value=None if new_value is None else str(new_value),
        source_document_id=source_document_id,
    ))


def _obligations_from(grant_data: GrantData) -> Iterable[dict]:
    """Reporting requirements, submission requirements and dated timeline
    entries, flattened into the one obligation shape.

    The three sources overlap: an award letter that states "Interim
    report due March 31, 2027" is picked up both as a reporting
    requirement and as a timeline entry. Emitting both would put two
    identical deadlines in Perch and two events in the calendar, so a
    timeline entry that duplicates an already-emitted (kind, date) is
    dropped. Requirements win because they carry required_elements and
    the reporting cadence; timeline entries carry neither.
    """
    seen: set[tuple[str, Any]] = set()
    for req in grant_data.reporting_requirements or []:
        title = (req.description or "").strip() or "Report"
        seen.add(("report", parse_date(req.due_date)))
        yield {
            "kind": "report",
            "title": title[:300],
            "due_date": parse_date(req.due_date),
            "due_date_raw": req.due_date,
            "required_elements": list(req.required_elements or []),
            "reporting_period": req.period,
        }
    for req in grant_data.submission_requirements or []:
        kind = _TIMELINE_KIND.get((req.category or "submission").lower(), "submission")
        seen.add((kind, parse_date(req.due_date)))
        yield {
            "kind": kind,
            "title": (req.instructions or req.category or "Submission").strip()[:300],
            "due_date": parse_date(req.due_date),
            "due_date_raw": req.due_date,
            "lead_time_days": req.lead_time_days,
            "next_day_follow_up": req.next_day_follow_up,
            "instructions": req.instructions,
        }
    timeline = getattr(grant_data.timeline, "items", None) or []
    for item in timeline:
        kind = _TIMELINE_KIND.get((item.category or "").lower())
        if not kind:
            continue
        due = parse_date(item.date)
        # A dateless timeline entry cannot be matched against anything, so
        # it is kept only when it is not obviously a restatement.
        if due is not None and (kind, due) in seen:
            continue
        seen.add((kind, due))
        yield {
            "kind": kind,
            "title": (item.description or "Timeline item").strip()[:300],
            "due_date": parse_date(item.date),
            "due_date_raw": item.date,
            "amount": to_decimal(item.amount),
            "instructions": item.notes,
        }


def persist_grant(db: Session, grant_data: GrantData, *, tenant_id: UUID,
                  user_id: UUID, document_id: Optional[UUID] = None,
                  machine_values: Optional[dict] = None,
                  edits: Optional[dict] = None) -> cm.Grant:
    """Write a confirmed extraction into core. Caller commits.

    Only the whitelist crosses. An obligation whose date could not be
    parsed is still written — with due_date NULL and the raw string kept —
    because a requirement you cannot date is exactly the thing a reviewer
    needs to see, not something to silently drop.
    """
    period_start, period_end = parse_period(grant_data.grant_period)
    grant = cm.Grant(
        tenant_id=tenant_id,
        funder_name_raw=grant_data.funder_name,
        title=grant_data.grant_title,
        grant_ref=grant_data.grant_name,
        purpose=grant_data.purpose,
        amount=to_decimal(grant_data.grant_amount),
        period_start=period_start,
        period_end=period_end,
        period_raw=grant_data.grant_period,
        status="active",
        extraction_method=grant_data.extraction_method,
        used_external_llm=bool(grant_data.used_external_llm),
        validation_flags=list(grant_data.validation_flags or []),
        data_gaps=list(grant_data.data_gaps or []),
        source_document_id=document_id,
        confirmed_by=user_id,
        confirmed_at=datetime.utcnow(),
        revision=1 + len(edits or {}),
    )
    db.add(grant)
    db.flush()

    machine_values = machine_values or {}
    edits = edits or {}
    for field in PERSISTED_SCALARS:
        prov = (grant_data.field_provenance or {}).get(field)
        current = _scalar(grant_data, field)
        # machine_value is the extractor's claim, written once. If a
        # reviewer changed the field, the current value is theirs and is
        # recorded alongside — never over — the original.
        machine = machine_values.get(field, current)
        edited = edits.get(field)
        human = current if edited else None
        db.add(cm.GrantFieldProvenance(
            grant_id=grant.id,
            field_name=field,
            machine_value=machine,
            confidence="confirmed" if edited else _confidence(grant_data, field),
            source_kind=getattr(getattr(prov, "source_document", None), "value",
                                getattr(prov, "source_document", None)) or None,
            quote=getattr(prov, "quote", None),
            human_value=human,
            edited_by=user_id if edited else None,
            edited_at=datetime.utcnow() if edited else None,
        ))
        if edited and human != machine:
            audit(db, tenant_id=tenant_id, actor_user_id=user_id, action="update",
                  table="grant_field_provenance", entity_id=grant.id, field=field,
                  old_value=machine, new_value=human)

    for contact in (grant_data.contacts or [])[:20]:
        db.add(cm.GrantContact(
            grant_id=grant.id, name=contact.name, title=contact.title,
            organization=contact.organization, email=contact.email,
            phone=contact.phone, role=contact.role))

    budget_items = getattr(grant_data.budget, "items", None) or []
    for order, item in enumerate(budget_items):
        amount = to_decimal(item.amount)
        if amount is None:
            continue
        db.add(cm.GrantBudgetLine(
            grant_id=grant.id, category=item.category, amount=amount,
            description=item.description, timeline_hint=item.timeline, sort_order=order))

    tasks = getattr(grant_data.workplan, "tasks", None) or []
    for order, task in enumerate(tasks):
        db.add(cm.GrantWorkplanTask(
            grant_id=grant.id, task_name=task.task_name, description=task.description,
            start_date=parse_date(task.start_date), end_date=parse_date(task.end_date),
            responsible_party=task.responsible_party, deliverables=task.deliverables,
            sort_order=order))

    for spec in _obligations_from(grant_data):
        if spec.get("due_date") is None and not spec.get("due_date_raw"):
            continue  # nothing to track and nothing for a reviewer to fix
        db.add(cm.Obligation(
            tenant_id=tenant_id, grant_id=grant.id,
            kind=spec["kind"], title=spec["title"],
            due_date=spec.get("due_date"),
            due_date_raw=spec.get("due_date_raw"),
            amount=spec.get("amount"),
            lead_time_days=spec.get("lead_time_days", 7),
            next_day_follow_up=spec.get("next_day_follow_up", True),
            instructions=spec.get("instructions"),
            required_elements=spec.get("required_elements") or [],
            reporting_period=spec.get("reporting_period"),
            origin="award_letter",
            source_document_id=document_id,
            confidence="inferred",
        ))

    # Everything is staged on the session but not yet committed: check the
    # actual values before they can land.
    db.flush()
    written: list[Any] = []
    for obj in db.new | db.dirty:
        for column in obj.__table__.columns:
            written.append(getattr(obj, column.name, None))
    assert_no_leak(grant_data, written)

    audit(db, tenant_id=tenant_id, actor_user_id=user_id, action="create",
          table="grants", entity_id=grant.id, source_document_id=document_id,
          new_value=grant_data.grant_title)
    return grant
