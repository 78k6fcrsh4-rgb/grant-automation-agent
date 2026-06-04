"""LLM-first grant extraction.

Design (see Extraction_Review_and_Recommendations.md):
  * The LLM, constrained by an explicit schema + disambiguation rules, is the
    PRIMARY extractor. It reads "Awardee", "by and between", fill-in blanks and
    signature blocks natively, so no document-format detection is required.
  * The regex LocalExtractionService result is passed in as `base_data` and used
    only to (a) fill fields the LLM leaves empty and (b) provide a fallback when
    no API key is configured.
  * Every scalar field carries provenance (value + confidence + source document +
    verbatim quote) so a reviewer can see WHY a value was chosen.
  * Deterministic validators flag suspicious values (threshold amounts, signature
    dates mistaken for the term) instead of letting them pass silently.
  * Full document text is sent (capped by LLM_MAX_INPUT_CHARS, default 120k chars)
    rather than the old 12k/8k truncation.
"""
import json
import os
import re
from typing import Dict, List, Optional

from dotenv import load_dotenv

from app.models.schemas import (
    Budget,
    BudgetItem,
    ContactInfo,
    ExtractionConfidence,
    FieldProvenance,
    GrantData,
    ReportingRequirement,
    SourceDocument,
    SubmissionRequirement,
    Timeline,
    TimelineItem,
    WorkPlan,
    WorkPlanTask,
)
from app.services import classification, validation

load_dotenv()

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"


def _max_input_chars() -> int:
    try:
        return int(os.getenv("LLM_MAX_INPUT_CHARS", "120000"))
    except ValueError:
        return 120000


_SCALAR_FIELDS = (
    "organization_name", "grant_title", "grant_amount", "grant_period",
    "funder_name", "purpose",
)

_SYSTEM_PROMPT = """You are a meticulous grants-management analyst. You extract structured \
post-award data from grant documents (proposals and award letters / agreements). \
You return ONLY a single valid JSON object — no prose, no markdown fences.

AUTHORITY & SOURCES
- The award letter / grant agreement is AUTHORITATIVE. When the proposal and the \
award letter conflict on any field, use the award letter.
- The proposal fills in detail the award letter omits (purpose narrative, program \
description, detailed work plan, reporting specifics).

DISAMBIGUATION RULES (these are the mistakes to avoid)
1. grant_amount = the dollar figure actually awarded to THIS awardee. NEVER use a \
threshold or eligibility figure such as "for awards of $20,000 or less", and NEVER \
use the total project/program cost or the funder's overall budget. If the document \
says e.g. "providing Awardee with a funding award in the amount of $33,600", the \
amount is 33600.
2. grant_period = the performance term (e.g. a fiscal year such as "FY2026" or \
"July 1 2025 – June 30 2026"). It is NOT the effective date and NOT the signature \
date. A span of only a few days/weeks is almost always wrong.
3. organization_name (the awardee/grantee) may appear ONLY as a filled-in blank \
after "by and between", or in the signature block — extract it from there. Do not \
confuse it with the funder. funder_name is the body MAKING the award.
4. grant_title = the program/project name (often from the proposal, e.g. a named \
program). It is NOT the funder's name and NOT the document type.
5. reporting_requirements = explicit obligations the grantee must perform ("shall \
submit", "will invoice", "must report", "agrees to provide"). Capture conditional \
rules too (e.g. "awards of $20,000 or less require only one report"). Exclude pure \
boilerplate (indemnification, governing law, insurance) UNLESS it imposes a concrete \
deliverable.

CONFIDENCE
- "confirmed": value is explicit in the text.
- "inferred": derived from context; could be wrong.
- "missing": not found — use null for value.
For every scalar field provide a short verbatim "quote" you took the value from."""

_SCHEMA_INSTRUCTIONS = """Return EXACTLY this JSON shape:
{
  "document_classification": "proposal | award_letter | combined | unknown",
  "organization_name": {"value": string|null, "confidence": "confirmed|inferred|missing", "source_document": "proposal|award_letter|null", "quote": string|null},
  "funder_name":       {"value": string|null, "confidence": "...", "source_document": "...", "quote": string|null},
  "grant_title":       {"value": string|null, "confidence": "...", "source_document": "...", "quote": string|null},
  "grant_amount":      {"value": number|null, "confidence": "...", "source_document": "...", "quote": string|null},
  "grant_period":      {"value": string|null, "confidence": "...", "source_document": "...", "quote": string|null},
  "purpose":           {"value": string|null, "confidence": "...", "source_document": "...", "quote": string|null},
  "timeline": [ {"date": string, "amount": string|null, "description": string, "category": string|null, "source_document": "proposal|award_letter|null", "notes": string|null} ],
  "budget": {"total_grant_amount": number, "items": [ {"category": string, "amount": number, "description": string|null, "timeline": string|null} ]},
  "workplan": {"project_title": string, "grant_period": string, "tasks": [ {"task_name": string, "description": string, "start_date": string|null, "end_date": string|null, "responsible_party": string|null, "deliverables": string|null} ]},
  "reporting_requirements": [ {"period": "quarterly|semi-annual|annual|as-requested|null", "due_date": "YYYY-MM-DD|null", "description": string, "required_elements": [string]} ],
  "submission_requirements": [ {"category": string, "due_date": "YYYY-MM-DD|null", "instructions": string|null} ],
  "contacts": [ {"name": string|null, "title": string|null, "organization": string|null, "email": string|null, "phone": string|null, "role": string|null} ]
}"""


class LLMService:
    """Optional external reasoning layer. Primary extractor when available."""

    def __init__(self):
        self._llm = None
        self._init_attempted = False

    # ------------------------------------------------------------------ setup
    def is_available(self) -> bool:
        if DEMO_MODE:
            return True
        if self._init_attempted:
            return self._llm is not None
        self._init_attempted = True
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return False
        try:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
                temperature=0,
                api_key=api_key,
                request_timeout=90,
                max_tokens=4096,
            )
            return True
        except Exception:
            self._llm = None
            return False

    # ----------------------------------------------------------- classification
    def classify_document(self, text: str) -> str:
        """Classify a single document. LLM when available, heuristic fallback."""
        heuristic = classification.heuristic_classify(text)
        if DEMO_MODE or not self.is_available():
            return heuristic
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            msgs = [
                SystemMessage(content=(
                    "Classify the grant document as exactly one word: 'proposal', "
                    "'award_letter', 'combined', or 'unknown'. A proposal/application "
                    "asks for funding; an award_letter/agreement grants it (signatures, "
                    "'by and between', 'in the amount of'). Reply with the one word only."
                )),
                HumanMessage(content=text[:6000]),
            ]
            resp = self._llm.invoke(msgs).content.strip().lower()
            for label in ("combined", "award_letter", "proposal", "unknown"):
                if label in resp:
                    return label
        except Exception:
            pass
        return heuristic

    # ------------------------------------------------------------------ extract
    def enrich_grant_data(
        self,
        base_data: GrantData,
        *,
        sanitized_text: str,
        source_documents: Optional[List[SourceDocument]] = None,
        award_text: Optional[str] = None,
    ) -> GrantData:
        """Primary entry point used by the routes. base_data is the regex result."""
        source_documents = source_documents or base_data.source_documents
        if DEMO_MODE:
            return self._demo_enrichment(base_data, sanitized_text, source_documents)
        if not self.is_available():
            # No LLM: keep regex result but still run validators so reviewers are warned.
            return self._finalize_regex_only(base_data, award_text, sanitized_text)

        cap = _max_input_chars()
        full_text = (sanitized_text or base_data.raw_text or "")[:cap]
        award_section = (award_text or "")[:cap]
        truncated = len(sanitized_text or "") > cap

        payload = self._invoke_extraction(full_text, award_section)
        if payload is None:
            # LLM failed/invalid JSON -> fall back to regex result, flagged.
            result = self._finalize_regex_only(base_data, award_text, sanitized_text)
            reason = getattr(self, "_last_error", None) or "unknown error"
            result.validation_flags = ([f"LLM extraction failed ({reason}); showing "
                                        f"regex-only results — review carefully."] + result.validation_flags)
            return result

        return self._build_from_llm(
            base_data, payload, source_documents,
            award_text=award_section or full_text,
            full_text=full_text,
            truncated=truncated,
        )

    def _invoke_extraction(self, full_text: str, award_section: str) -> Optional[Dict]:
        from langchain_core.messages import HumanMessage, SystemMessage

        award_block = (
            f"\n=== AWARD LETTER / AGREEMENT (AUTHORITATIVE) ===\n{award_section}\n"
            if award_section else ""
        )
        human = (
            f"{_SCHEMA_INSTRUCTIONS}\n{award_block}\n"
            f"=== FULL DOCUMENT TEXT ===\n{full_text}\n\n"
            f"Return the JSON object now."
        )
        msgs = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human)]

        self._last_error = None
        for attempt in range(2):  # one retry on bad JSON
            try:
                raw = self._llm.invoke(msgs).content
            except Exception as e:
                self._last_error = f"{type(e).__name__}: {str(e)[:300]}"
                return None
            parsed = self._parse_json(raw)
            if parsed is not None:
                return parsed
            msgs.append(HumanMessage(content="That was not valid JSON. Reply with ONLY the JSON object."))
        self._last_error = "Model replied with invalid JSON twice"
        return None

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict]:
        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        # Grab the outermost JSON object if the model added stray text.
        if not text.startswith("{"):
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                text = m.group(0)
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    # ----------------------------------------------------------------- builders
    def _build_from_llm(self, base_data, payload, source_documents, *,
                        award_text, full_text, truncated) -> GrantData:
        provenance: Dict[str, FieldProvenance] = {}
        confidence: Dict[str, str] = {}
        scalars: Dict[str, object] = {}

        for field in _SCALAR_FIELDS:
            node = payload.get(field) or {}
            if not isinstance(node, dict):
                node = {"value": node}
            value = node.get("value")
            if field == "grant_amount":
                value = self._coerce_amount(value)
            base_val = getattr(base_data, field, None)
            final_val = value if value not in (None, "", 0) else base_val
            conf = (node.get("confidence") or "missing").lower()
            if conf not in ("confirmed", "inferred", "missing"):
                conf = "inferred"
            if final_val in (None, "", 0):
                conf = "missing"
            elif value in (None, "", 0) and base_val not in (None, "", 0):
                conf = "inferred"  # came from regex fallback
            scalars[field] = final_val
            confidence[field] = conf
            provenance[field] = FieldProvenance(
                value=str(final_val) if final_val not in (None, "") else None,
                confidence=ExtractionConfidence(conf),
                source_document=self._coerce_dockind(node.get("source_document")),
                quote=(node.get("quote") or None),
            )

        timeline_items = [self._mk(TimelineItem, i) for i in payload.get("timeline") or []]
        timeline_items = [t for t in timeline_items if t]
        if not timeline_items and base_data.timeline:
            timeline_items = base_data.timeline.items

        budget = self._build_budget(payload.get("budget"), scalars["grant_amount"], base_data)
        workplan = self._build_workplan(payload.get("workplan"), scalars, timeline_items, base_data)

        reporting = [self._mk(ReportingRequirement, r) for r in payload.get("reporting_requirements") or []]
        reporting = [r for r in reporting if r] or base_data.reporting_requirements

        submissions = [self._mk(SubmissionRequirement, s) for s in payload.get("submission_requirements") or []]
        submissions = [s for s in submissions if s] or base_data.submission_requirements

        contacts = [self._mk(ContactInfo, c) for c in payload.get("contacts") or []]
        contacts = [c for c in contacts if c] or base_data.contacts

        flags = validation.validate_extraction(
            grant_amount=scalars["grant_amount"],
            grant_period=scalars["grant_period"],
            organization_name=scalars["organization_name"],
            reporting_count=len(reporting),
            award_text=award_text,
            full_text=full_text,
        )
        if truncated:
            flags.append("Document text exceeded the LLM input cap and was truncated; "
                         "raise LLM_MAX_INPUT_CHARS if fields look incomplete.")

        doc_class = payload.get("document_classification") or base_data.document_type

        return GrantData(
            **base_data.model_dump(exclude={
                "timeline", "budget", "workplan", "reporting_requirements",
                "submission_requirements", "contacts", "field_provenance",
                "validation_flags", "extraction_confidence", "extraction_method",
                *(_SCALAR_FIELDS), "grant_name", "document_type", "used_external_llm",
                "source_documents",
            }),
            organization_name=scalars["organization_name"],
            grant_title=scalars["grant_title"],
            grant_amount=scalars["grant_amount"],
            grant_period=scalars["grant_period"],
            funder_name=scalars["funder_name"],
            purpose=scalars["purpose"],
            grant_name=scalars["grant_title"],
            document_type=base_data.document_type or doc_class,
            source_documents=source_documents,
            used_external_llm=True,
            timeline=Timeline(items=timeline_items),
            budget=budget,
            workplan=workplan,
            reporting_requirements=reporting,
            submission_requirements=submissions,
            contacts=contacts,
            extraction_confidence=confidence,
            field_provenance=provenance,
            validation_flags=flags,
            extraction_method="llm+regex",
        )

    def _finalize_regex_only(self, base_data: GrantData, award_text, sanitized_text) -> GrantData:
        flags = validation.validate_extraction(
            grant_amount=base_data.grant_amount,
            grant_period=base_data.grant_period,
            organization_name=base_data.organization_name,
            reporting_count=len(base_data.reporting_requirements or []),
            award_text=award_text or "",
            full_text=sanitized_text or base_data.raw_text or "",
        )
        data = base_data.model_copy(deep=True)
        data.validation_flags = flags
        data.extraction_method = "regex"
        return data

    def validate_only(self, base_data, *, award_text=None, sanitized_text=None):
        """Public: attach validator flags to a regex-only result (LLM disabled)."""
        return self._finalize_regex_only(base_data, award_text, sanitized_text)

    # ------------------------------------------------------------------ helpers
    def _build_budget(self, node, grant_amount, base_data) -> Budget:
        node = node or {}
        items = [self._mk(BudgetItem, i) for i in node.get("items") or []]
        items = [i for i in items if i]
        total = self._coerce_amount(node.get("total_grant_amount")) or grant_amount or 0.0
        if not items and base_data.budget and base_data.budget.items:
            return base_data.budget
        return Budget(total_grant_amount=total or 0.0, items=items)

    def _build_workplan(self, node, scalars, timeline_items, base_data) -> WorkPlan:
        node = node or {}
        tasks = [self._mk(WorkPlanTask, t) for t in node.get("tasks") or []]
        tasks = [t for t in tasks if t]
        if not tasks and base_data.workplan and base_data.workplan.tasks:
            return base_data.workplan
        return WorkPlan(
            project_title=node.get("project_title") or scalars.get("grant_title") or "Project Plan",
            grant_period=node.get("grant_period") or scalars.get("grant_period") or "To Be Determined",
            tasks=tasks,
        )

    @staticmethod
    def _mk(model, data):
        """Construct a pydantic model from a dict, dropping unknown/invalid rows."""
        if not isinstance(data, dict):
            return None
        try:
            allowed = {k: v for k, v in data.items() if k in model.model_fields}
            return model(**allowed)
        except Exception:
            return None

    @staticmethod
    def _coerce_dockind(value):
        if value in ("proposal", "award_letter", "combined", "unknown"):
            return value
        return None

    @staticmethod
    def _coerce_amount(value) -> Optional[float]:
        if value in (None, "", 0):
            return None
        if isinstance(value, (float, int)):
            return float(value)
        cleaned = re.sub(r"[^\d.]", "", str(value))
        return float(cleaned) if cleaned else None

    # --------------------------------------------------------------------- demo
    def _demo_enrichment(self, base_data, sanitized_text, source_documents) -> GrantData:
        items = list(base_data.timeline.items if base_data.timeline else [])
        if not items:
            match = re.search(
                r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
                sanitized_text or "",
            )
            if match:
                items.append(TimelineItem(date=match.group(0), description="Demo milestone", category="milestone"))
        return GrantData(
            **base_data.model_dump(exclude={"timeline", "source_documents", "used_external_llm", "extraction_method"}),
            used_external_llm=True,
            source_documents=source_documents,
            timeline=Timeline(items=items),
            extraction_method="demo",
        )
