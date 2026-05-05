import json
import os
import re
from typing import Dict, List, Optional
from dotenv import load_dotenv
from app.models.schemas import (
    Budget,
    GrantData,
    ReportingRequirement,
    SourceDocument,
    SubmissionRequirement,
    Timeline,
    TimelineItem,
    WorkPlan,
    WorkPlanTask,
)

load_dotenv()

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"


class LLMService:
    """Optional external reasoning layer over sanitized grant text."""

    def __init__(self):
        self._llm = None
        self._init_attempted = False

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
                request_timeout=60,
                max_tokens=3500,
            )
            return True
        except Exception:
            self._llm = None
            return False

    def enrich_grant_data(
        self,
        base_data: GrantData,
        *,
        sanitized_text: str,
        source_documents: Optional[List[SourceDocument]] = None,
        award_text: Optional[str] = None,
    ) -> GrantData:
        if DEMO_MODE:
            return self._demo_enrichment(base_data, sanitized_text, source_documents or [])
        if not self.is_available():
            return base_data

        from langchain_core.prompts import ChatPromptTemplate

        # Build award letter section for prompt (if available)
        award_section = (
            f"\nAward letter / grant agreement (AUTHORITATIVE — use this over the proposal for all fields):\n{award_text[:8000]}\n"
            if award_text
            else ""
        )

        prompt = ChatPromptTemplate.from_template(
            """You are extracting structured grant management data from redacted grant documents.
Return valid JSON only — no explanation, no markdown fences.

CRITICAL RULES:
1. The award letter / grant agreement is the authoritative source. If proposal and award letter conflict, always use the award letter values.
2. reporting_requirements: Extract ONLY explicit obligations — sentences where the grantee is required/obligated to submit, provide, or report something. Look for language like "required to submit", "shall submit", "agrees to provide", "must provide", "will provide". Do NOT include purpose descriptions, insurance clauses, or general boilerplate. Each item must describe what the grantee must actually do.
3. budget: Extract ONLY what the award letter explicitly states about financial terms and disbursement (e.g. total amount, payment schedule, invoicing frequency). Do NOT infer budget line items from proposal categories. If the award letter has no line-item breakdown, return budget with total_grant_amount only and empty items array.
4. grant_amount: The total dollar value awarded. Use only the award letter figure if available.
5. grant_period: The performance period (e.g. "2025-2026", "July 1 2025 – June 30 2026"). Use award letter dates.
6. Improve any field left as null/empty by local extraction where the redacted text provides clear evidence.
{award_section}
Full redacted grant text (supplementary context):
{text}

Local extraction snapshot (starting point — improve where you have clear evidence):
{local_json}

Return JSON:
{{
  "organization_name": "",
  "grant_title": "",
  "grant_amount": 0,
  "grant_period": "",
  "funder_name": "",
  "timeline": [],
  "budget": {{"total_grant_amount": 0, "items": []}},
  "workplan": {{"project_title": "", "grant_period": "", "tasks": []}},
  "reporting_requirements": [
    {{
      "period": "quarterly or semi-annual or annual or as-requested or null",
      "due_date": "YYYY-MM-DD or null",
      "description": "Exact obligation: what the grantee must submit or provide",
      "required_elements": []
    }}
  ],
  "submission_requirements": []
}}"""
        )
        chain = prompt | self._llm
        response = chain.invoke({
            "text": sanitized_text[:12000],
            "local_json": base_data.model_dump_json(indent=2),
            "award_section": award_section,
        })
        response_text = response.content.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        try:
            payload = json.loads(response_text.strip())
        except json.JSONDecodeError:
            return base_data
        return self._merge(base_data, payload, source_documents or base_data.source_documents)

    def _merge(self, base_data: GrantData, payload: Dict, source_documents: List[SourceDocument]) -> GrantData:
        timeline_items = [TimelineItem(**item) for item in payload.get("timeline", [])] if payload.get("timeline") else base_data.timeline.items if base_data.timeline else []
        budget_data = payload.get("budget") or {}
        workplan_data = payload.get("workplan") or {}
        reporting = [ReportingRequirement(**item) for item in payload.get("reporting_requirements", [])] if payload.get("reporting_requirements") else base_data.reporting_requirements
        submissions = [SubmissionRequirement(**item) for item in payload.get("submission_requirements", [])] if payload.get("submission_requirements") else base_data.submission_requirements
        return GrantData(
            **base_data.model_dump(exclude={"timeline", "budget", "workplan", "reporting_requirements", "submission_requirements"}),
            organization_name=payload.get("organization_name") or base_data.organization_name,
            grant_title=payload.get("grant_title") or base_data.grant_title,
            grant_amount=self._coerce_amount(payload.get("grant_amount")) or base_data.grant_amount,
            grant_period=payload.get("grant_period") or base_data.grant_period,
            funder_name=payload.get("funder_name") or base_data.funder_name,
            source_documents=source_documents,
            used_external_llm=True,
            timeline=Timeline(items=timeline_items),
            budget=Budget(**budget_data) if budget_data else base_data.budget,
            workplan=WorkPlan(**workplan_data) if workplan_data else base_data.workplan,
            reporting_requirements=reporting,
            submission_requirements=submissions,
        )

    def _demo_enrichment(self, base_data: GrantData, sanitized_text: str, source_documents: List[SourceDocument]) -> GrantData:
        items = list(base_data.timeline.items if base_data.timeline else [])
        if not items:
            match = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}", sanitized_text)
            if match:
                items.append(TimelineItem(date=match.group(0), description="Demo milestone from redacted text", category="milestone"))
        return GrantData(
            **base_data.model_dump(exclude={"timeline"}),
            used_external_llm=True,
            source_documents=source_documents,
            timeline=Timeline(items=items),
        )

    @staticmethod
    def _coerce_amount(value) -> Optional[float]:
        if value in (None, "", 0):
            return None
        if isinstance(value, (float, int)):
            return float(value)
        cleaned = re.sub(r"[^\d.]", "", str(value))
        return float(cleaned) if cleaned else None
