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
    ) -> GrantData:
        if DEMO_MODE:
            return self._demo_enrichment(base_data, sanitized_text, source_documents or [])
        if not self.is_available():
            return base_data

        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template(
            """
You are reviewing grant materials that have already been locally parsed and redacted.
Do not assume access to raw names, salaries, or contact details.
Return valid JSON only.

Use the structured local extraction as your starting point and improve only what can be supported by the redacted text.
Prefer explicit dates and requirements from the award letter if available.

Redacted grant text:
{text}

Local extraction snapshot:
{local_json}

Return JSON with this shape:
{{
  "organization_name": "",
  "grant_title": "",
  "grant_amount": 0,
  "grant_period": "",
  "funder_name": "",
  "timeline": [],
  "budget": {{"total_grant_amount": 0, "items": []}},
  "workplan": {{"project_title": "", "grant_period": "", "tasks": []}},
  "reporting_requirements": [],
  "submission_requirements": []
}}
"""
        )
        chain = prompt | self._llm
        response = chain.invoke({"text": sanitized_text[:18000], "local_json": base_data.model_dump_json(indent=2)})
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
