import re
from typing import List, Tuple
from app.models.schemas import PrivacySettings, RedactionEntity, TransmissionPreview


# Lines that contain these words are salary/budget table rows — amounts on them should be redacted.
_SALARY_INDICATOR = re.compile(
    r"\b(?:salary|salaries|wage|wages|compensation|stipend|fringe|benefit|benefits"
    r"|fte|annual\s+cost|per\s+year|per\s+hour|hourly|payroll|personnel\s+cost)\b",
    re.IGNORECASE,
)

# Lines that contain these words are grant-award lines — amounts on them must NOT be redacted
# even if redact_salaries is on.
_AWARD_INDICATOR = re.compile(
    r"\b(?:award(?:ed)?(?:\s+amount)?|grant(?:\s+amount)?|total\s+award|total\s+grant"
    r"|disbursement|allocation|budget\s+total|award\s+total|contract\s+amount"
    r"|approved\s+amount|grant\s+of|amount\s+of\s+\$|amount:\s*\$)\b",
    re.IGNORECASE,
)

_DOLLAR_PATTERN = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
_PERCENT_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%\b")


class PrivacyService:
    def redact_text(self, text: str, settings: PrivacySettings) -> Tuple[str, List[RedactionEntity]]:
        redacted = text
        entities: List[RedactionEntity] = []

        def apply(pattern: str, placeholder_base: str, entity_type: str, flags: int = 0):
            """Global replacement — used for unambiguous PII (emails, phones, EINs, SSNs)."""
            nonlocal redacted, entities
            matches = re.findall(pattern, redacted, flags)
            if not matches:
                return
            flat = [m[0] if isinstance(m, tuple) else m for m in matches]
            unique = []
            for item in flat:
                cleaned = item.strip()
                if cleaned and cleaned not in unique:
                    unique.append(cleaned)
            for idx, original in enumerate(unique, start=1):
                placeholder = f"[{placeholder_base}_{idx:02d}]"
                count = len(re.findall(re.escape(original), redacted))
                redacted = re.sub(re.escape(original), placeholder, redacted)
                entities.append(
                    RedactionEntity(
                        entity_type=entity_type,
                        placeholder=placeholder,
                        original_preview=self._preview(original),
                        count=count,
                    )
                )

        # ── Contact details ─────────────────────────────────────────────────
        if settings.redact_contact_details:
            apply(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "EMAIL", "email")
            apply(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})", "PHONE", "phone")
            apply(r"\b\d{2}-\d{7}\b", "EIN", "tax_id")
            apply(r"\b\d{3}-\d{2}-\d{4}\b", "SSN", "ssn")

        # ── Salary / compensation amounts ────────────────────────────────────
        # Strategy: redact dollar amounts and percentages ONLY on lines that
        # contain salary/compensation keywords AND do NOT contain award-amount
        # keywords.  This prevents award totals (e.g. "Award Amount: $25,000")
        # from being masked while still protecting budget salary rows.
        if settings.redact_salaries:
            redacted, new_entities = self._redact_salary_lines(redacted)
            entities.extend(new_entities)

        # ── Names ───────────────────────────────────────────────────────────
        # Purpose: protect staff identities when names appear in a budget or
        # next to compensation figures.  We deliberately do NOT redact:
        #   • Names in letter salutations / closings (public signatories)
        #   • Recipient organisation contacts on award letters
        # We DO redact:
        #   • Names introduced by a role label (Director:, PI:, etc.) on a
        #     line that also contains a dollar amount — i.e. a budget table row.
        if settings.redact_names:
            redacted, new_entities = self._redact_budget_names(redacted)
            entities.extend(new_entities)

        entities.sort(key=lambda x: (x.entity_type, x.placeholder))
        return redacted, entities

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _redact_salary_lines(self, text: str) -> Tuple[str, List[RedactionEntity]]:
        """Redact dollar amounts and percentages on salary-context lines only."""
        entities: List[RedactionEntity] = []
        # Track replacements so we can assign sequential placeholders
        salary_amounts: List[str] = []
        percent_amounts: List[str] = []

        lines = text.split("\n")
        new_lines = []
        for line in lines:
            if _SALARY_INDICATOR.search(line) and not _AWARD_INDICATOR.search(line):
                # Collect unique dollar amounts from this line
                for m in _DOLLAR_PATTERN.findall(line):
                    if m not in salary_amounts:
                        salary_amounts.append(m)
                for m in _PERCENT_PATTERN.findall(line):
                    if m not in percent_amounts:
                        percent_amounts.append(m)
            new_lines.append(line)

        # Now do replacements on the full text (so duplicates across lines are
        # consistently replaced with the same placeholder)
        result = "\n".join(new_lines)
        for idx, original in enumerate(salary_amounts, start=1):
            placeholder = f"[SALARY_{idx:02d}]"
            count = len(re.findall(re.escape(original), result))
            result = re.sub(re.escape(original), placeholder, result)
            entities.append(RedactionEntity(
                entity_type="currency",
                placeholder=placeholder,
                original_preview=self._preview(original),
                count=count,
            ))
        for idx, original in enumerate(percent_amounts, start=1):
            placeholder = f"[PERCENT_{idx:02d}]"
            count = len(re.findall(re.escape(original), result))
            result = re.sub(re.escape(original), placeholder, result)
            entities.append(RedactionEntity(
                entity_type="percentage",
                placeholder=placeholder,
                original_preview=self._preview(original),
                count=count,
            ))
        return result, entities

    def _redact_budget_names(self, text: str) -> Tuple[str, List[RedactionEntity]]:
        """Redact person names only when they appear on budget/salary table lines.

        A 'budget name line' is one that:
          - contains a role label (Director, PI, etc.) followed by a name, AND
          - also contains a dollar amount or percentage (i.e. looks like a budget row)

        This deliberately preserves names in:
          - Letter closings ("Sincerely, Andrea Saenz")
          - Address blocks ("Attn: Patricia Herbst")
          - Award notification text ("pleased to inform … Patricia Herbst")
        """
        role_name_re = re.compile(
            r"(?:Project Director|Executive Director|Program Director|Principal Investigator"
            r"|Finance Manager|CFO|CEO|COO|Director|Manager|Coordinator|Consultant"
            r"|Staff|Employee|Position)\s*[:\-]?\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)",
        )
        has_dollar_or_pct = re.compile(r"\$|\[SALARY_|\[PERCENT_|\b\d+(?:\.\d+)?%\b")

        entities: List[RedactionEntity] = []
        found_names: List[str] = []

        for line in text.split("\n"):
            if has_dollar_or_pct.search(line):
                for m in role_name_re.finditer(line):
                    name = m.group(1).strip()
                    if name and name not in found_names:
                        found_names.append(name)

        result = text
        for idx, name in enumerate(found_names, start=1):
            placeholder = f"[PERSON_{idx:02d}]"
            count = len(re.findall(re.escape(name), result))
            if count:
                result = re.sub(re.escape(name), placeholder, result)
                entities.append(RedactionEntity(
                    entity_type="person_name",
                    placeholder=placeholder,
                    original_preview=self._preview(name),
                    count=count,
                ))
        return result, entities

    def build_transmission_preview(
        self,
        raw_text: str,
        redacted_text: str,
        structured_fields_count: int,
        external_llm_enabled: bool,
    ) -> TransmissionPreview:
        payload_excerpt = redacted_text[:1200]
        notes = [
            "Raw uploaded text stays in the local application environment.",
            "Only redacted text and structured grant facts are eligible for external LLM analysis.",
        ]
        if not external_llm_enabled:
            notes.append(
                "External LLM analysis is off. Results shown are based on local parsing and rules."
            )
        return TransmissionPreview(
            external_llm_enabled=external_llm_enabled,
            raw_characters=len(raw_text),
            redacted_characters=len(redacted_text),
            structured_fields_count=structured_fields_count,
            excerpt_count=1 if payload_excerpt else 0,
            payload_excerpt=payload_excerpt,
            notes=notes,
        )

    @staticmethod
    def _preview(value: str) -> str:
        value = value.strip()
        if len(value) <= 24:
            return value
        return value[:10] + "…" + value[-6:]
