import re
from typing import List, Optional, Dict, Tuple
from app.models.schemas import (
    Budget,
    BudgetItem,
    ContactInfo,
    ExtractionConfidence,
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
        """
        Main extraction method. Detects document format and routes to appropriate extractors.
        """
        # Detect document format first
        document_format = self._detect_document_format(text)

        # Prepare basic candidate lists
        date_candidates = self._unique(self.date_pattern.findall(text))[:12]
        amount_candidates = self._unique(self.amount_pattern.findall(text))[:12]
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # Extract based on document format
        if document_format == "federal_noa":
            organization_name, org_confidence = self._extract_grantee_federal(lines)
            funder_name, funder_confidence = self._extract_funder_federal(lines, text)
            grant_title, title_confidence = self._extract_grant_title_federal(lines)
            purpose, purpose_confidence = self._extract_purpose_federal(lines, text)
            grant_name, grant_name_confidence = self._extract_grant_name_federal(lines)
            reporting_requirements = self._extract_reporting_federal(lines)
        elif document_format == "grant_agreement":
            organization_name, org_confidence = self._extract_grantee_grant_agreement(lines)
            funder_name, funder_confidence = self._extract_funder_grant_agreement(lines)
            grant_title, title_confidence = self._extract_grant_title_grant_agreement(lines, text)
            purpose, purpose_confidence = self._extract_purpose_grant_agreement(lines, text)
            grant_name, grant_name_confidence = grant_title, title_confidence
            reporting_requirements = self._extract_reporting_letter(lines)
        elif document_format == "contract":
            organization_name, org_confidence = self._extract_grantee_contract(lines)
            funder_name, funder_confidence = self._extract_funder_contract(lines)
            grant_title, title_confidence = self._extract_grant_title_contract(lines)
            purpose, purpose_confidence = self._extract_purpose_contract(lines, text)
            grant_name, grant_name_confidence = grant_title, title_confidence
            reporting_requirements = []
        else:  # letter format (default)
            organization_name, org_confidence = self._extract_grantee_letter(lines)
            funder_name, funder_confidence = self._extract_funder_letter(lines, text)
            grant_title, title_confidence = self._extract_grant_title_letter(lines, text)
            purpose, purpose_confidence = self._extract_purpose_letter(lines, text)
            grant_name, grant_name_confidence = grant_title, title_confidence
            reporting_requirements = self._extract_reporting_letter(lines)

        # Common extractors (work for all formats)
        grant_amount = self._first_amount(amount_candidates)
        grant_period = self._extract_grant_period(lines, date_candidates)
        timeline_items = self._extract_timeline(lines)
        submission_requirements = self._extract_submissions(lines)
        contacts = self._extract_contacts(lines, text)

        # Build helper structures
        workplan = self._build_workplan(grant_title, grant_period, timeline_items)
        budget = self._build_budget(grant_amount, amount_candidates, lines)

        # Build extraction confidence tracking
        extraction_confidence = self._build_extraction_confidence(
            organization_name, org_confidence,
            funder_name, funder_confidence,
            grant_title, title_confidence,
            purpose, purpose_confidence,
            grant_amount,
            grant_period,
        )

        # Build data gaps list
        data_gaps = self._build_data_gaps(
            organization_name, funder_name, grant_amount, grant_period,
            reporting_requirements, document_format
        )

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
            purpose=purpose,
            grant_name=grant_name,
            contacts=contacts,
            extraction_confidence=extraction_confidence,
            data_gaps=data_gaps,
            document_format=document_format,
        )

    def _detect_document_format(self, text: str) -> str:
        """Detect document format: federal_noa, grant_agreement, contract, or letter."""
        text_upper = text.upper()

        if "NOTICE OF AWARD" in text_upper or "FEDERAL AWARD ID" in text_upper or "FAIN" in text_upper:
            return "federal_noa"

        # Grant agreements: explicit GRANTEE/GRANTOR labels, or BETWEEN/AND structure
        if (("GRANTEE:" in text_upper and "GRANTOR:" in text_upper)
                or "(GRANTEE)" in text_upper
                or ("BETWEEN" in text_upper and "GRANTOR" in text_upper)):
            return "grant_agreement"

        if "DELEGATE AGENCY:" in text_upper or "RELEASE PACKAGE" in text_upper or "PURCHASE ORDER NUMBER:" in text_upper:
            return "contract"

        return "letter"

    # ===== LETTER FORMAT EXTRACTORS =====

    # Pronouns and generic words to reject as grantee matches
    _GENERIC_WORDS = re.compile(r"^(?:your|our|their|this|the|a|an|its)\b", re.IGNORECASE)

    def _extract_grantee_letter(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grantee from letter format."""
        full_text = "\n".join(lines)
        flat = re.sub(r"\n", " ", full_text)

        # 1. Address block: line before "Attn:" (most reliable)
        for i, line in enumerate(lines):
            if re.match(r"Attn[\s:.]", line, re.IGNORECASE) and i > 0:
                candidate = lines[i - 1].strip()
                if candidate and not re.search(r"\d{5}", candidate) and len(candidate) > 3:
                    return (candidate[:120], ExtractionConfidence.CONFIRMED)

        # 2. Address block without Attn: — line before a street/city line (typical letter layout:
        #    Org name, [contact name,] [title,] street, city state zip, Dear X)
        for i, line in enumerate(lines):
            if re.match(r"Dear\b", line, re.IGNORECASE) and i >= 2:
                # Walk backwards from "Dear" to find the org name (skip address lines)
                for k in range(i - 1, max(i - 6, -1), -1):
                    candidate = lines[k].strip()
                    # Skip lines that look like street/city addresses or personal names/titles
                    if re.search(r"\d{5}", candidate):
                        continue  # zip code line
                    if re.search(r"^\d+\s+[A-Z]", candidate):
                        continue  # street number
                    if re.search(r"\b(?:Director|Manager|Coordinator|Suite|Ste|Rd|Ave|Blvd|St\b|Dr\b)\b", candidate, re.IGNORECASE):
                        continue
                    # Accept if it looks like an org name (has org-type word or comma-Inc/LLC pattern)
                    if re.search(r"\b(?:Inc|LLC|Foundation|Services|Center|Institute|Council|Association)\b", candidate, re.IGNORECASE):
                        return (candidate[:120], ExtractionConfidence.CONFIRMED)
                break

        # 3. Precise position patterns: "approved for [Org] in the amount" / "grant of $X to [Org]"
        #    These give us exactly the grantee with a strong stop condition.
        m = re.search(
            r"(?:approved for|grant of \$[\d,]+\s+to)\s+([A-Z][A-Za-z &,'./-]{3,}?)(?:\s+in\s+the\s+amount|\s+has|\.|$)",
            flat, re.IGNORECASE,
        )
        if m:
            candidate = m.group(1).strip()
            if not self._GENERIC_WORDS.match(candidate) and len(candidate) > 4:
                return (candidate[:120], ExtractionConfidence.CONFIRMED)

        # 4. "[Org] has been awarded/approved" — less precise, used as fallback
        #    Require org-indicator word so we don't pick up grant title phrases.
        org_indicator_re = re.compile(
            r"\b(?:Inc|LLC|Foundation|Services|Center|Institute|Council|Association|Organization|Corp|Trust)\b",
            re.IGNORECASE,
        )
        m = re.search(r"([A-Z][A-Za-z &,'./-]{3,}?)\s+has been (?:awarded|approved)", flat)
        if m:
            candidate = m.group(1).strip()
            if not self._GENERIC_WORDS.match(candidate) and len(candidate) > 4 and org_indicator_re.search(candidate):
                return (candidate[:120], ExtractionConfidence.CONFIRMED)

        # 5. Explicit label
        for line in lines[:20]:
            if re.search(r"organization|grantee|recipient", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1:
                    return (parts[1].strip()[:120], ExtractionConfidence.INFERRED)

        return (None, ExtractionConfidence.MISSING)

    def _extract_funder_letter(self, lines: List[str], text: str) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract funder from letter format (signature block and letterhead)."""
        # Look for signature block: after "Sincerely," etc., skip first line, find org indicator
        signature_keywords = ["Sincerely", "Respectfully", "Regards", "Yours truly", "Yours sincerely", "Best regards"]

        org_sig_re = re.compile(
            r"\b(?:Foundation|Fund|Institute|Trust|Association|Corporation|Corp|Inc|LLC"
            r"|Organization|Society|Council|Group|Agency|University|College|Services|Community)\b"
        )
        for i, line in enumerate(lines):
            if any(re.search(rf"\b{kw}[,\.]?", line, re.IGNORECASE) for kw in signature_keywords):
                # Skip the signatory's personal name (i+1), check subsequent lines for org
                for j in range(i + 2, min(i + 6, len(lines))):
                    candidate = lines[j].strip()
                    if not org_sig_re.search(candidate) or len(candidate) <= 3 or len(candidate) >= 120:
                        continue
                    # If line has "Title, Org Name" format (comma separating title from org), take org part
                    if re.match(r"(?:President|CEO|Director|Officer|Administrator|Manager|Coordinator)", candidate, re.IGNORECASE):
                        m = re.search(r",\s*(.+)$", candidate)
                        if m and org_sig_re.search(m.group(1)):
                            return (m.group(1).strip(), ExtractionConfidence.CONFIRMED)
                    return (candidate, ExtractionConfidence.CONFIRMED)

        # "On behalf of [The] Funder Name," — check before letterhead (more precise)
        m = re.search(
            r"[Oo]n behalf of\s+(?:[Tt]he\s+)?([A-Z][A-Za-z &,'./-]+?)(?:,|\.\s|\s+[Ii]\s|\s+[Ww]e\s|$)",
            text,
        )
        if m:
            return (m.group(1).strip()[:120], ExtractionConfidence.CONFIRMED)

        # Letterhead: first 8 lines containing org-type word
        org_re = re.compile(
            r"\b(?:Foundation|Fund|Institute|Trust|Association|Corporation|Corp|Inc|LLC"
            r"|Organization|Society|Council|Group|Agency|University|College|Services|Community)\b"
        )
        for line in lines[:8]:
            if org_re.search(line) and 3 < len(line) < 120:
                return (re.sub(r"\s{2,}", " ", line).strip(), ExtractionConfidence.INFERRED)

        # Fallback: explicit label
        for line in lines[:25]:
            if re.search(r"\bfunder\b|awarded by|grantor", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1:
                    return (parts[1].strip()[:120], ExtractionConfidence.INFERRED)

        return (None, ExtractionConfidence.MISSING)

    def _extract_grant_title_letter(self, lines: List[str], text: str) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grant title from letter format."""
        # "application titled X" / "project titled X" / "titled 'X'"
        m = re.search(
            r'(?:application|project|grant|program)?\s*(?:titled|entitled|called|named)\s*["\u201c]?'
            r'([^"\u201d\n,\.]{4,80}?)'
            r'(?=["\u201d]|\s+(?:over|in order|to be|that|which|for a|\$)|$)',
            text, re.IGNORECASE,
        )
        if m:
            return (m.group(1).strip()[:160], ExtractionConfidence.CONFIRMED)

        # Multi-year grant pattern: "2024-2029 Multi-Year Grant" (stop before "commitment", "has", "was")
        m = re.search(
            r"(\d{4}[-–]\d{4}\s+[\w\s-]{5,50}?(?:Grant|Fund|Award|Program))(?:\s+(?:has|was|will|is|commitment)|[,\.]|$)",
            text, re.IGNORECASE
        )
        if m:
            return (m.group(1).strip()[:160], ExtractionConfidence.INFERRED)

        # Explicit label lines
        for line in lines[:30]:
            if re.search(r"grant title|project title|program title|project name", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1:
                    return (parts[1].strip()[:160], ExtractionConfidence.CONFIRMED)

        # Fallback: short title-cased line near the top (skip date/address lines)
        _addr_re = re.compile(r"\b(?:Rd|St|Ave|Blvd|Dr|Ste|Suite|Lane|Ln|Way|Ct|Pl|Place|Pkwy|Hwy)\b", re.IGNORECASE)
        for line in lines[:10]:
            if 8 < len(line) < 160 and line == line.title():
                # Skip pure date lines
                if re.search(
                    r"^\s*(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                    r"\s+\d{1,2},?\s+\d{4}\s*$",
                    line, re.IGNORECASE,
                ):
                    continue
                # Skip address lines (contain street suffix abbreviations or zip codes)
                if _addr_re.search(line) or re.search(r"\b\d{5}\b", line):
                    continue
                # Skip salutation lines
                if re.match(r"Dear\b", line, re.IGNORECASE):
                    continue
                return (line, ExtractionConfidence.INFERRED)

        return (None, ExtractionConfidence.MISSING)

    def _extract_purpose_letter(self, lines: List[str], text: str) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grant purpose from letter format."""
        # "for [purpose]" after grant amount
        m = re.search(r"amount\s+of\s+\$[\d,\.]+\s+for\s+([^,\.\n]+)", text, re.IGNORECASE)
        if m:
            return (m.group(1).strip()[:200], ExtractionConfidence.CONFIRMED)

        # "Grant Purpose:" label
        for line in lines:
            if re.search(r"grant purpose:", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1:
                    return (parts[1].strip()[:200], ExtractionConfidence.CONFIRMED)

        # Common phrases
        if "unrestricted general support" in text.lower():
            return ("Unrestricted general support", ExtractionConfidence.INFERRED)
        if "general operations" in text.lower():
            return ("General operations", ExtractionConfidence.INFERRED)

        return (None, ExtractionConfidence.MISSING)

    def _extract_grant_name_letter(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract explicit grant name from letter format (separate from title)."""
        # "Grant ID:" or similar
        for line in lines:
            if re.search(r"grant\s+(?:id|name|identifier)", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    return (parts[1].strip()[:160], ExtractionConfidence.CONFIRMED)
        return (None, ExtractionConfidence.MISSING)

    def _extract_reporting_letter(self, lines: List[str]) -> List[ReportingRequirement]:
        """Extract reporting requirements from letter format."""
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

                # Extract requirement name if present (e.g., "Mid-Year PPR", "Final Report")
                name_match = re.search(r"([A-Za-z\s-]+(?:Report|PPR|Summary))", line, re.IGNORECASE)
                description = name_match.group(1).strip() if name_match else line[:220]

                requirements.append(
                    ReportingRequirement(
                        period=period,
                        due_date=due,
                        description=description,
                        required_elements=self._infer_required_elements(line),
                    )
                )

        return requirements[:6]

    # ===== FEDERAL NOA FORMAT EXTRACTORS =====

    def _extract_grantee_federal(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grantee from federal NOA format."""
        # 1. Address block before Attn:
        for i, line in enumerate(lines):
            if re.match(r"Attn[\s:.]", line, re.IGNORECASE) and i > 0:
                candidate = lines[i - 1].strip()
                if candidate and not re.search(r"\d{5}", candidate) and len(candidate) > 3:
                    return (candidate[:120], ExtractionConfidence.CONFIRMED)

        # 2. GAN/NOA labels: "RECIPIENT NAME" / "GRANTEE NAME:" (label on one line, value on next)
        for i, line in enumerate(lines):
            if re.match(r"^\s*(?:RECIPIENT\s+NAME|GRANTEE\s+NAME)\s*:?\s*$", line, re.IGNORECASE):
                if i + 1 < len(lines):
                    candidate = lines[i + 1].strip()
                    if candidate and len(candidate) > 3 and not re.match(r"^\d+$", candidate):
                        return (candidate[:120], ExtractionConfidence.CONFIRMED)
            elif re.match(r"^\s*(?:RECIPIENT\s+NAME|GRANTEE\s+NAME)\s*:", line, re.IGNORECASE):
                parts = line.split(":", 1)
                val = parts[1].strip() if len(parts) > 1 else ""
                if val and len(val) > 3:
                    return (val[:120], ExtractionConfidence.CONFIRMED)

        # 3. Address block before "Dear" — pattern: Name+Title, ORG NAME, Street, City/State
        #    Walk backwards from "Dear" skipping address lines to find the org name
        _org_words_re = re.compile(
            r"\b(?:Inc|LLC|Foundation|Services|Center|Institute|Council|Association"
            r"|Network|Consortium|Clinic|Health|Agency|Corp|School|University|College)\b",
            re.IGNORECASE,
        )
        for i, line in enumerate(lines):
            if re.match(r"Dear\b", line, re.IGNORECASE) and i >= 3:
                for k in range(i - 1, max(i - 10, -1), -1):
                    candidate = lines[k].strip()
                    if not candidate:
                        continue
                    if re.search(r"\d{5}", candidate):  # zip code line
                        continue
                    if re.search(r"^\d+\s+[A-Z]", candidate):  # street number
                        continue
                    # Skip "Name, Title" lines
                    if re.search(
                        r",\s*(?:Director|Officer|Manager|Coordinator|Administrator"
                        r"|President|Chief|Dr\b|PhD|Executive|Superintendent)",
                        candidate, re.IGNORECASE,
                    ):
                        continue
                    if _org_words_re.search(candidate):
                        return (candidate[:120], ExtractionConfidence.CONFIRMED)
                break

        # Fallback to letter method
        return self._extract_grantee_letter(lines)

    def _extract_funder_federal(self, lines: List[str], text: str) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract funder from federal NOA format — signature block org is most precise."""
        # 1. Signature block — keyword must START the line (re.match) to avoid mid-doc false matches
        sig_re = re.compile(r"^\s*(?:Respectfully|Sincerely|Regards)\b", re.IGNORECASE)
        dept_re = re.compile(r"\b(?:Department|Administration|Agency|Office|Services|Bureau|Commission)\b", re.IGNORECASE)
        for i, line in enumerate(lines):
            if sig_re.match(line):
                for j in range(i + 2, min(i + 7, len(lines))):
                    candidate = lines[j].strip()
                    if dept_re.search(candidate) and 5 < len(candidate) < 120:
                        return (candidate, ExtractionConfidence.CONFIRMED)

        # 2. Specific known federal agencies — search HEADER area only (first 40 lines)
        #    to avoid matching boilerplate references mid-document
        specific_agencies = [
            "Administration for Community Living",
            "Administration for Children and Families",
            "Substance Abuse and Mental Health Services Administration",
            "Centers for Disease Control",
            "National Institutes of Health",
            "Department of Education",
            "Department of Health and Human Services",
            "Department of Housing and Urban Development",
            "Department of Justice",
            "Department of Labor",
        ]
        header_text = "\n".join(lines[:50]).lower()
        for agency in specific_agencies:
            if agency.lower() in header_text:
                return (agency, ExtractionConfidence.CONFIRMED)

        # 3. Header department lines (first 10 lines)
        for line in lines[:10]:
            if dept_re.search(line) and 5 < len(line) < 120:
                return (line.strip(), ExtractionConfidence.INFERRED)

        return (None, ExtractionConfidence.MISSING)

    def _extract_grant_title_federal(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grant title from federal NOA format (Project Title field).
        Handles inline, next-line, and wrapped values (title continues on line after)."""
        _section_header_re = re.compile(r"^(?:[A-Z][A-Z\s]{2,}|[A-Z][a-z]+\s*:|\d+\s*[A-Z])")
        for i, line in enumerate(lines):
            if re.search(r"project title:", line, re.IGNORECASE):
                parts = re.split(r":", line, maxsplit=1)
                value = parts[1].strip() if len(parts) > 1 else ""
                next_line_used = False
                if not value and i + 1 < len(lines):
                    value = lines[i + 1].strip()
                    next_line_used = True
                # Check continuation — start from i+1 if value was inline, i+2 if from next line
                start = (i + 2) if next_line_used else (i + 1)
                for cont_idx in range(start, min(start + 2, len(lines))):
                    nxt = lines[cont_idx].strip()
                    if (nxt and not _section_header_re.match(nxt)
                            and not self.date_pattern.search(nxt)
                            and nxt not in value):
                        value = (value + " " + nxt).strip()
                    else:
                        break
                if value:
                    return (value[:200], ExtractionConfidence.CONFIRMED)
        return (None, ExtractionConfidence.MISSING)

    def _extract_purpose_federal(self, lines: List[str], text: str) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract purpose from federal NOA format."""
        # Look in body text after award notification
        m = re.search(
            r"(?:to\s+support|in support of|for\s+the|project\s+designed\s+to)\s+([^,\.\n]{10,200})",
            text, re.IGNORECASE
        )
        if m:
            return (m.group(1).strip()[:200], ExtractionConfidence.INFERRED)

        return (None, ExtractionConfidence.MISSING)

    def _extract_grant_name_federal(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grant name from federal NOA (often the program title)."""
        for line in lines:
            if re.search(r"program title:", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1:
                    return (parts[1].strip()[:160], ExtractionConfidence.CONFIRMED)
        return (None, ExtractionConfidence.MISSING)

    def _extract_reporting_federal(self, lines: List[str]) -> List[ReportingRequirement]:
        """Extract reporting requirements from federal NOA format."""
        requirements: List[ReportingRequirement] = []

        # Broad date pattern for report due dates: "October 1, 2026" or "1 October 2026"
        report_date_re = re.compile(
            r"(?:[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            re.IGNORECASE,
        )

        in_reporting_section = False
        for i, line in enumerate(lines):
            if re.search(r"REPORTING REQUIREMENTS", line, re.IGNORECASE):
                in_reporting_section = True
                continue

            if in_reporting_section:
                # Stop at next numbered section header like "V. CONTACTS" or "CONTACTS"
                if re.match(r"^(?:[IVXLC]+\.\s+|[A-Z]{3,}\s*$)", line.strip()) and len(line.strip()) > 2:
                    # Only stop if not a report line itself
                    if not re.search(r"due|report|submit", line, re.IGNORECASE):
                        break

                # Pattern 1: "Report Name: Due DATE" or "Report Name (abbrev): Due DATE"
                m = re.search(r"^(.{5,80}?):\s+[Dd]ue\s+(.+)$", line)
                if m:
                    date_m = report_date_re.search(m.group(2))
                    requirements.append(
                        ReportingRequirement(
                            period=None,
                            due_date=date_m.group(0) if date_m else m.group(2).strip()[:50],
                            description=m.group(1).strip(),
                            required_elements=[],
                        )
                    )
                    continue

                # Pattern 2: standalone date line that follows a named report
                if report_date_re.search(line) and requirements:
                    last = requirements[-1]
                    if not last.due_date:
                        date_m = report_date_re.search(line)
                        last.due_date = date_m.group(0) if date_m else None

        return requirements[:8]

    # ===== CONTRACT FORMAT EXTRACTORS =====

    def _extract_grantee_contract(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grantee from contract format (Delegate Agency field)."""
        for i, line in enumerate(lines):
            if re.search(r"delegate agency:", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    return (parts[1].strip()[:120], ExtractionConfidence.CONFIRMED)
                # Value may be on the next line (OCR/layout split)
                if i + 1 < len(lines):
                    next_val = lines[i + 1].strip()
                    if next_val and len(next_val) > 3 and not re.match(r"^\d+$", next_val):
                        return (next_val[:120], ExtractionConfidence.CONFIRMED)

        return (None, ExtractionConfidence.MISSING)

    def _extract_funder_contract(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract funder from contract format (header info)."""
        # "Department of Family and Support Services" may span two lines due to OCR/layout
        for i, line in enumerate(lines[:20]):
            # Check for multi-line "Department of\nX Services" pattern
            if re.search(r"\bDepartment of\s*$", line, re.IGNORECASE) and i + 1 < len(lines):
                joined = (line.strip() + " " + lines[i + 1].strip())
                return (joined[:120], ExtractionConfidence.CONFIRMED)

            # Single-line "Department of X"
            m = re.search(r"((?:City of \w+\s+)?Department of [A-Za-z &]+)", line, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip()
                # Skip bare "Department of" without a name
                if len(candidate.split()) > 2:
                    return (candidate[:120], ExtractionConfidence.CONFIRMED)

        return (None, ExtractionConfidence.MISSING)

    def _extract_grant_title_contract(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grant title from contract format."""
        for line in lines:
            if re.search(r"program name:|contract type:", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    return (parts[1].strip()[:160], ExtractionConfidence.CONFIRMED)

        return (None, ExtractionConfidence.MISSING)

    def _extract_purpose_contract(self, lines: List[str], text: str) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract purpose from contract format."""
        # Look for explicit purpose field
        for line in lines:
            if re.search(r"purpose:", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1:
                    return (parts[1].strip()[:200], ExtractionConfidence.CONFIRMED)

        return (None, ExtractionConfidence.MISSING)

    # ===== GRANT AGREEMENT FORMAT EXTRACTORS =====

    def _extract_grantee_grant_agreement(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grantee from grant agreement format.

        Handles:
          - Explicit GRANTEE: label (MacArthur-style, CCT-style)
          - "(Grantee)" inline marker (IYIP-style state agreements)
          - BETWEEN … AND … structure (state contracts)
        """
        # 1. GRANTEE: label — value inline or on next line
        for i, line in enumerate(lines):
            if re.match(r"^\s*GRANTEE\s*:", line, re.IGNORECASE):
                parts = line.split(":", 1)
                val = parts[1].strip() if len(parts) > 1 else ""
                if not val and i + 1 < len(lines):
                    val = lines[i + 1].strip()
                if val and len(val) > 3 and not re.match(r"^\d+$", val):
                    return (val[:120], ExtractionConfidence.CONFIRMED)

        # 2. "(Grantee)" inline — the preceding text on the line is the org name
        for line in lines:
            m = re.search(r"([A-Z][A-Za-z &,'.]+?)\s*\(Grantee\)", line)
            if m:
                candidate = m.group(1).strip().rstrip(",")
                if len(candidate) > 4:
                    return (candidate[:120], ExtractionConfidence.CONFIRMED)

        # 3. BETWEEN … AND … structure — grantee follows the "AND" separator
        for i, line in enumerate(lines):
            if re.match(r"^\s*BETWEEN\s*$", line.strip(), re.IGNORECASE):
                for j in range(i + 1, min(i + 25, len(lines))):
                    if re.match(r"^\s*AND\s*$", lines[j].strip(), re.IGNORECASE):
                        # Skip blank lines and page-number-only lines after AND
                        for k in range(j + 1, min(j + 10, len(lines))):
                            candidate = lines[k].strip()
                            if not candidate or re.match(r"^\d+$", candidate):
                                continue
                            return (candidate[:120], ExtractionConfidence.CONFIRMED)
                        break

        # Fallback
        return self._extract_grantee_letter(lines)

    def _extract_funder_grant_agreement(self, lines: List[str]) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract funder/grantor from grant agreement format."""
        # 1. GRANTOR: label — value inline or on next line
        for i, line in enumerate(lines):
            if re.match(r"^\s*GRANTOR\s*:", line, re.IGNORECASE):
                parts = line.split(":", 1)
                val = parts[1].strip() if len(parts) > 1 else ""
                if not val and i + 1 < len(lines):
                    val = lines[i + 1].strip()
                if val and len(val) > 3 and not re.match(r"^\d+$", val):
                    return (val[:120], ExtractionConfidence.CONFIRMED)

        # 2. "(Grantor)" inline
        for line in lines:
            m = re.search(r"([A-Z][A-Za-z &,'.]+?)\s*\(Grantor\)", line)
            if m:
                candidate = m.group(1).strip().rstrip(",")
                if len(candidate) > 4:
                    return (candidate[:120], ExtractionConfidence.CONFIRMED)

        # 3. BETWEEN … AND … structure — grantor is the party named AFTER "BETWEEN"
        for i, line in enumerate(lines):
            if re.match(r"^\s*BETWEEN\s*$", line.strip(), re.IGNORECASE):
                for j in range(i + 1, min(i + 5, len(lines))):
                    candidate = lines[j].strip()
                    if not candidate or re.match(r"^\d+$", candidate):
                        continue
                    return (candidate[:120], ExtractionConfidence.CONFIRMED)

        # Fallback
        return self._extract_funder_letter(lines, "\n".join(lines))

    def _extract_grant_title_grant_agreement(self, lines: List[str], text: str) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract grant/program title from grant agreement format."""
        for i, line in enumerate(lines):
            if re.search(r"grant name:|program name:|project name:|grant title:", line, re.IGNORECASE):
                parts = re.split(r":", line, maxsplit=1)
                val = parts[1].strip() if len(parts) > 1 else ""
                if not val and i + 1 < len(lines):
                    val = lines[i + 1].strip()
                if val and len(val) > 3:
                    return (val[:160], ExtractionConfidence.CONFIRMED)

        # Fallback to letter method
        return self._extract_grant_title_letter(lines, text)

    def _extract_purpose_grant_agreement(self, lines: List[str], text: str) -> Tuple[Optional[str], ExtractionConfidence]:
        """Extract purpose from grant agreement format."""
        for line in lines:
            if re.search(r"purpose:", line, re.IGNORECASE):
                parts = re.split(r":|-", line, maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    return (parts[1].strip()[:200], ExtractionConfidence.CONFIRMED)
        return self._extract_purpose_letter(lines, text)

    # ===== COMMON EXTRACTORS =====

    def _extract_grant_period(self, lines: List[str], dates: List[str]) -> Optional[str]:
        """Extract the grant term / performance period."""
        full_text = "\n".join(lines)

        # Explicit label AT START OF LINE: "grant period:", "period of performance:", etc.
        # Using match (or ^) to avoid matching mid-sentence "each year of the grant term describing..."
        for line in lines[:80]:
            if re.match(
                r"^\s*(?:grant period|period of performance|project period|grant term|budget term|budget period)\s*[:\-]",
                line, re.IGNORECASE,
            ):
                parts = re.split(r"[:\-]", line, maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    return parts[1].strip()[:180]

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

        # Year range like "2024-2029" or "2024–2029" (multi-year grant span)
        m = re.search(r"\b(20\d{2}[-\u2013](20\d{2}))\b", full_text)
        if m:
            return m.group(1)

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

    def _extract_contacts(self, lines: List[str], text: str) -> List[ContactInfo]:
        """Extract contact information from document."""
        contacts: List[ContactInfo] = []

        # Pattern for federal NOA style: "Role: Name | Organization | Phone | Email"
        pattern = r"(?:Program Officer|Grants Management Officer|Contact)[:\s]+([^|]+)\|([^|]+)\|([^|]+)\|([^\n]+)"
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            contact = ContactInfo(
                name=match.group(1).strip(),
                organization=match.group(2).strip(),
                phone=match.group(3).strip(),
                email=match.group(4).strip(),
                role=self._extract_contact_role(match.group(0))
            )
            contacts.append(contact)

        # Pattern for letter style: "please contact NAME"
        pattern = r"(?:please (?:contact|reach out to))\s+([A-Z][a-z]+\s+[A-Z][a-z]+)"
        matches = re.finditer(pattern, text)
        for match in matches:
            name = match.group(1)
            # Look for nearby email/phone
            email = None
            phone = None
            for line in lines:
                if name in line:
                    email_match = re.search(r"[\w\.-]+@[\w\.-]+", line)
                    phone_match = re.search(r"\(\d{3}\)\s?\d{3}-?\d{4}", line)
                    if email_match:
                        email = email_match.group(0)
                    if phone_match:
                        phone = phone_match.group(0)
                    break

            contact = ContactInfo(name=name, email=email, phone=phone)
            contacts.append(contact)

        return contacts[:5]

    def _extract_contact_role(self, text: str) -> Optional[str]:
        """Extract contact role from text."""
        if "program officer" in text.lower():
            return "program_officer"
        elif "grants management" in text.lower():
            return "grants_officer"
        elif "contact" in text.lower():
            return "contact"
        return None

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

    def _build_extraction_confidence(
        self,
        org_name: Optional[str], org_confidence: ExtractionConfidence,
        funder_name: Optional[str], funder_confidence: ExtractionConfidence,
        grant_title: Optional[str], title_confidence: ExtractionConfidence,
        purpose: Optional[str], purpose_confidence: ExtractionConfidence,
        grant_amount: Optional[float],
        grant_period: Optional[str],
    ) -> Dict[str, str]:
        """Build extraction confidence tracking dictionary."""
        confidence_map = {
            "organization_name": org_confidence.value if org_name else ExtractionConfidence.MISSING.value,
            "funder_name": funder_confidence.value if funder_name else ExtractionConfidence.MISSING.value,
            "grant_title": title_confidence.value if grant_title else ExtractionConfidence.MISSING.value,
            "purpose": purpose_confidence.value if purpose else ExtractionConfidence.MISSING.value,
            "grant_amount": ExtractionConfidence.CONFIRMED.value if grant_amount else ExtractionConfidence.MISSING.value,
            "grant_period": ExtractionConfidence.CONFIRMED.value if grant_period else ExtractionConfidence.MISSING.value,
        }
        return confidence_map

    def _build_data_gaps(
        self,
        org_name: Optional[str],
        funder_name: Optional[str],
        grant_amount: Optional[float],
        grant_period: Optional[str],
        reporting_requirements: List[ReportingRequirement],
        document_format: Optional[str],
    ) -> List[str]:
        """Build list of data gaps with specific reasons."""
        gaps = []

        if not org_name:
            gaps.append("Organization name not found — no address block or 'Attn:' pattern detected")

        if not funder_name:
            if document_format == "letter":
                gaps.append("Funder not found — no signature block with org indicator detected")
            else:
                gaps.append("Funder not found — no labeled program title or department field")

        if not grant_amount:
            gaps.append("Grant amount not found — no dollar amount pattern detected")

        if not grant_period:
            gaps.append("Grant period not found — no explicit dates or duration mentioned")

        if not reporting_requirements:
            if document_format in ("letter", "grant_agreement", None):
                gaps.append("Reporting requirements not found — letter does not mention reporting obligations")
            elif document_format == "federal_noa":
                gaps.append("Reporting requirements not found — no REPORTING REQUIREMENTS section detected")

        return gaps

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
