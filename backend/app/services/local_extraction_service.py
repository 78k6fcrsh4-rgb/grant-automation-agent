import re
from typing import List, Optional
from app.models.schemas import (
    Budget,
    BudgetItem,
    GrantData,
    LocalExtractionSummary,
    PrivacySettings,
    ReportingRequirement,
    SourceDocument,
    SubmissionRequirement,
    Timeline,
    TimelineItem,
    WorkPlan,
    WorkPlanTask,
)


class LocalExtractionService:
    # Matches: "March 31, 2027" · "March 31 2027" · "2 April 2026" · "31 March" · "12/31/2027"
    date_pattern = re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s+\d{4}\b"
        r"|\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August"
        r"|September|October|November|December)(?:\s+\d{4})?\b"
        r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        re.IGNORECASE,
    )
    amount_pattern = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?")

    def extract(
        self,
        text: str,
        *,
        source_documents: List[SourceDocument],
        proposal_text: Optional[str],
        award_letter_text: Optional[str],
        privacy_settings: PrivacySettings,
    ) -> GrantData:
        date_candidates = self._unique(self.date_pattern.findall(text))[:12]
        amount_candidates = self._unique(self.amount_pattern.findall(text))[:12]
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        organization_name = self._extract_org_name(lines)
        funder_name = self._extract_funder(lines)
        grant_title = self._extract_grant_title(lines)
        grant_amount = self._first_amount(amount_candidates)
        grant_period = self._extract_grant_period(lines, date_candidates)
        timeline_items = self._extract_timeline(lines)
        reporting_requirements = self._extract_reporting(lines)
        submission_requirements = self._extract_submissions(lines)
        workplan = self._build_workplan(grant_title, grant_period, timeline_items)
        budget = self._build_budget(grant_amount, amount_candidates, lines)

        summary = LocalExtractionSummary(
            grant_amount_candidates=amount_candidates[:5],
            date_candidates=date_candidates[:8],
            reporting_clues=self._find_lines(lines, ["report", "quarterly", "semi-annual", "annual"]),
            reimbursement_clues=self._find_lines(lines, ["reimburse", "disburse", "invoice", "payment"]),
            deliverable_clues=self._find_lines(lines, ["deliverable", "milestone", "status update", "meeting"]),
            unresolved_questions=self._build_questions(grant_amount, grant_period, timeline_items),
        )

        document_type = "combined" if proposal_text and award_letter_text else (
            "proposal" if proposal_text else "award_letter" if award_letter_text else "unknown"
        )

        return GrantData(
            organization_name=organization_name,
            grant_title=grant_title,
            grant_amount=grant_amount,
            grant_period=grant_period,
            funder_name=funder_name,
            document_type=document_type,
            source_documents=source_documents,
            proposal_text=proposal_text,
            award_letter_text=award_letter_text,
            privacy_settings=privacy_settings,
            local_extraction_summary=summary,
            used_external_llm=False,
            timeline=Timeline(items=timeline_items),
            budget=budget,
            workplan=workplan,
            reporting_requirements=reporting_requirements,
            submission_requirements=submission_requirements,
            raw_text=text,
        )

    def _extract_org_name(self, lines: List[str]) -> Optional[str]:
        """Extract the recipient organisation name from award letter or proposal text."""
        full_text = "\n".join(lines)

        # Address block: line immediately before "Attn:" is the most reliable signal
        # because OCR often splits multi-word org names across lines.
        for i, line in enumerate(lines):
            if re.match(r"Attn[\s:.]", line, re.IGNORECASE) and i > 0:
                candidate = lines[i - 1].strip()
                if candidate and not re.search(r"\d{5}", candidate) and len(candidate) > 3:
                    return candidate[:120]

        # "[Org] has been awarded …" — join adjacent lines so OCR breaks don't matter
        # Normalise by collapsing newlines to spaces for this search only
        flat = re.sub(r"\n", " ", full_text)
        m = re.search(
            r"([A-Z][A-Za-z &,'./-]{3,}?)\s+has been awarded",
            flat,
        )
        if m:
            return m.group(1).strip()[:120]

        # "awarded to [Org]" / "grant to [Org]"
        m = re.search(
            r"(?:awarded|grant)\s+to\s+([A-Z][A-Za-z &,'./-]+?)(?:\.|,|\s+to\s|\s+in\s|\s+for\s|$)",
            flat, re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()[:120]

        # Fallback: explicit label
        for line in lines[:20]:
            if re.search(r"organization|grantee|recipient", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1:
                    return parts[1].strip()[:120]
        return None

    def _extract_funder(self, lines: List[str]) -> Optional[str]:
        """Extract the funding organisation name."""
        full_text = "\n".join(lines)

        # "On behalf of [The] Funder Name, …"
        m = re.search(
            r"[Oo]n behalf of\s+(?:[Tt]he\s+)?([A-Z][A-Za-z &,'./-]+?)(?:,|\.\s|\s+[Ii]\s|\s+[Ww]e\s|$)",
            full_text,
        )
        if m:
            return m.group(1).strip()[:120]

        # Letterhead: first 8 lines containing a common org-type word
        org_re = re.compile(
            r"\b(?:Foundation|Fund|Institute|Trust|Association|Corporation|Corp|Inc|LLC"
            r"|Organization|Society|Council|Group|Agency|University|College|Charitable)\b"
        )
        for line in lines[:8]:
            if org_re.search(line) and 3 < len(line) < 120:
                return re.sub(r"\s{2,}", " ", line).strip()

        # Fallback: explicit label
        for line in lines[:25]:
            if re.search(r"\bfunder\b|awarded by|grantor", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1:
                    return parts[1].strip()[:120]
        return None

    def _extract_grant_title(self, lines: List[str]) -> Optional[str]:
        """Extract the grant or project title."""
        full_text = "\n".join(lines)

        # "application titled X" / "project titled X" / "titled 'X'"
        # Stop before continuation phrases like "over a period", "in order to", etc.
        m = re.search(
            r'(?:application|project|grant|program)?\s*(?:titled|entitled|called|named)\s*["\u201c]?'
            r'([^"\u201d\n,\.]{4,80}?)'
            r'(?=["\u201d]|\s+(?:over|in order|to be|that|which|for a|\$)|$)',
            full_text, re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()[:160]

        # Explicit label lines
        for line in lines[:30]:
            if re.search(r"grant title|project title|program title|project name", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1:
                    return parts[1].strip()[:160]

        # Fallback: short title-cased line near the top
        for line in lines[:10]:
            if 8 < len(line) < 160 and line == line.title():
                return line
        return None

    def _extract_grant_period(self, lines: List[str], dates: List[str]) -> Optional[str]:
        """Extract the grant term / performance period."""
        full_text = "\n".join(lines)

        # Explicit label: "grant period:", "period of performance:", etc.
        for line in lines[:80]:
            if re.search(r"grant period|period of performance|project period|grant term", line, re.IGNORECASE):
                return line[:180]

        # "over a period of X year(s) / month(s)"
        m = re.search(
            r"over\s+(?:a\s+)?period\s+of\s+(\d+\s+(?:year|month|week)s?)",
            full_text, re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()

        # "X-year grant" / "X year grant"
        m = re.search(r"(\d+)[\s-]?year\s+grant", full_text, re.IGNORECASE)
        if m:
            return f"{m.group(1)} year"

        # "from DATE to/through/until DATE" or "effective DATE – DATE"
        m = re.search(
            r"(?:from|effective)\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})"
            r"\s+(?:to|through|until|[-\u2013])\s+"
            r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            full_text, re.IGNORECASE,
        )
        if m:
            return f"{m.group(1)} \u2013 {m.group(2)}"

        # "expended by DATE" / "no later than DATE"
        m = re.search(
            r"(?:expended\s+by|no\s+later\s+than)\s+"
            r"(\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?|[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            full_text, re.IGNORECASE,
        )
        if m:
            return f"by {m.group(1).strip()}"

        # Fall back to first two dates found in the document
        if len(dates) >= 2:
            return f"{dates[0]} \u2013 {dates[1]}"
        return None

    def _extract_timeline(self, lines: List[str]) -> List[TimelineItem]:
        items: List[TimelineItem] = []
        keywords = {
            "report": "report",
            "reimburse": "reimbursement",
            "disburse": "disbursement",
            "deliverable": "deliverable",
            "milestone": "milestone",
            "meeting": "meeting",
            "deadline": "deadline",
            "invoice": "submission",
            "status update": "meeting",
        }
        for line in lines:
            dates = self.date_pattern.findall(line)
            if not dates:
                continue
            lower = line.lower()
            category = None
            for keyword, mapped in keywords.items():
                if keyword in lower:
                    category = mapped
                    break
            if not category:
                continue
            items.append(
                TimelineItem(
                    date=dates[0],
                    amount=(self.amount_pattern.search(line).group(0) if self.amount_pattern.search(line) else None),
                    description=line[:220],
                    category=category,
                    notes="Derived from local parsing; confirm exact due rule before submission.",
                )
            )
        deduped: List[TimelineItem] = []
        seen = set()
        for item in items:
            key = (item.date, item.description)
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped[:15]

    def _extract_reporting(self, lines: List[str]) -> List[ReportingRequirement]:
        requirements: List[ReportingRequirement] = []
        for line in lines:
            if re.search(r"quarterly|semi-annual|annual|report", line, re.IGNORECASE):
                due = self._first_date(line)
                period = None
                if re.search(r"quarterly", line, re.IGNORECASE):
                    period = "quarterly"
                elif re.search(r"semi-annual", line, re.IGNORECASE):
                    period = "semi-annual"
                elif re.search(r"annual", line, re.IGNORECASE):
                    period = "annual"
                requirements.append(
                    ReportingRequirement(
                        period=period,
                        due_date=due,
                        description=line[:220],
                        required_elements=self._infer_required_elements(line),
                    )
                )
        return requirements[:6]

    def _extract_submissions(self, lines: List[str]) -> List[SubmissionRequirement]:
        results: List[SubmissionRequirement] = []
        for line in lines:
            lower = line.lower()
            if any(word in lower for word in ["reimburse", "disburse", "invoice", "submit"]):
                category = "reimbursement" if "reimburse" in lower else "disbursement" if "disburse" in lower else "submission"
                results.append(
                    SubmissionRequirement(
                        category=category,
                        due_date=self._first_date(line),
                        instructions=line[:220],
                    )
                )
        return results[:8]

    def _build_workplan(self, grant_title: Optional[str], grant_period: Optional[str], timeline_items: List[TimelineItem]) -> WorkPlan:
        tasks: List[WorkPlanTask] = []
        if timeline_items:
            for item in timeline_items[:8]:
                tasks.append(
                    WorkPlanTask(
                        task_name=item.category.title() if item.category else "Grant task",
                        description=item.description,
                        start_date=item.date,
                        end_date=item.date,
                        responsible_party="Grant manager",
                        deliverables=item.notes or item.description,
                    )
                )
        else:
            tasks = [
                WorkPlanTask(
                    task_name="Review grant package",
                    description="Confirm all award requirements, deliverables, and payment rules from the uploaded files.",
                    responsible_party="Grant manager",
                ),
                WorkPlanTask(
                    task_name="Build reporting calendar",
                    description="Translate grant requirements into a working cadence for status updates, reporting, and reimbursement tracking.",
                    responsible_party="Program and finance leads",
                ),
            ]
        return WorkPlan(
            project_title=grant_title or "Grant implementation plan",
            grant_period=grant_period or "To be confirmed",
            tasks=tasks,
        )

    def _build_budget(self, grant_amount: Optional[float], amounts: List[str], lines: List[str]) -> Budget:
        items: List[BudgetItem] = []
        for line in lines:
            if re.search(r"personnel|fringe|travel|supplies|consultant|equipment", line, re.IGNORECASE) and self.amount_pattern.search(line):
                amount = self._first_amount([self.amount_pattern.search(line).group(0)]) or 0.0
                category = re.split(r":|-", line, maxsplit=1)[0][:80]
                items.append(BudgetItem(category=category, amount=amount, description=line[:220]))
        total = grant_amount or (self._first_amount(amounts[:1]) if amounts else 0.0) or 0.0
        return Budget(total_grant_amount=total, items=items[:12])

    def _infer_required_elements(self, line: str) -> List[str]:
        elements = []
        if re.search(r"financial", line, re.IGNORECASE):
            elements.append("financial summary")
        if re.search(r"narrative", line, re.IGNORECASE):
            elements.append("program narrative")
        if re.search(r"invoice|receipt|documentation", line, re.IGNORECASE):
            elements.append("supporting documentation")
        return elements

    def _build_questions(self, grant_amount: Optional[float], grant_period: Optional[str], timeline_items: List[TimelineItem]) -> List[str]:
        questions = []
        if not grant_amount:
            questions.append("Grant amount was not identified confidently from local parsing.")
        if not grant_period:
            questions.append("Grant period should be confirmed from the award letter.")
        if not timeline_items:
            questions.append("No dated reporting or reimbursement events were confidently extracted.")
        return questions

    def _find_lines(self, lines: List[str], keywords: List[str]) -> List[str]:
        results = []
        for line in lines:
            if any(keyword in line.lower() for keyword in keywords):
                results.append(line[:220])
        return self._unique(results)[:6]

    def _first_amount(self, amounts: List[str]) -> Optional[float]:
        if not amounts:
            return None
        cleaned = re.sub(r"[^\d.]", "", amounts[0])
        return float(cleaned) if cleaned else None

    def _first_date(self, text: str) -> Optional[str]:
        match = self.date_pattern.search(text)
        return match.group(0) if match else None

    @staticmethod
    def _unique(items: List[str]) -> List[str]:
        seen = set()
        ordered = []
        for item in items:
            normalized = item.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)
        return ordered
