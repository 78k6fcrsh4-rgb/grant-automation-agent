import re
from typing import List, Tuple
from app.models.schemas import PrivacySettings, RedactionEntity, TransmissionPreview


class PrivacyService:
    def redact_text(self, text: str, settings: PrivacySettings) -> Tuple[str, List[RedactionEntity]]:
        redacted = text
        entities: List[RedactionEntity] = []

        def apply(pattern: str, placeholder_base: str, entity_type: str, flags: int = 0):
            nonlocal redacted, entities
            matches = re.findall(pattern, redacted, flags)
            if not matches:
                return
            if matches and isinstance(matches[0], tuple):
                flat = [m[0] for m in matches if m and m[0]]
            else:
                flat = list(matches)
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

        if settings.redact_contact_details:
            apply(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "EMAIL", "email")
            apply(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})", "PHONE", "phone")
            apply(r"\b\d{2}-\d{7}\b", "EIN", "tax_id")
            apply(r"\b\d{3}-\d{2}-\d{4}\b", "SSN", "ssn")

        if settings.redact_salaries:
            apply(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?", "SALARY", "currency")
            apply(r"\b\d+(?:\.\d+)?%\b", "PERCENT", "percentage")

        if settings.redact_names:
            apply(r"(?:Project Director|Executive Director|Program Director|Principal Investigator|Finance Manager|CFO|CEO|Director|Manager|Coordinator|Consultant)\s*[:\-]?\s*([A-Z][a-z]+\s[A-Z][a-z]+)", "PERSON", "person_name")
            apply(r"(?:Sincerely|Signed|Signature|Approved by)[:,\s\n]+([A-Z][a-z]+\s[A-Z][a-z]+)", "PERSON", "signature_name", flags=re.MULTILINE)

        entities.sort(key=lambda x: (x.entity_type, x.placeholder))
        return redacted, entities

    def build_transmission_preview(self, raw_text: str, redacted_text: str, structured_fields_count: int, external_llm_enabled: bool) -> TransmissionPreview:
        payload_excerpt = redacted_text[:1200]
        notes = [
            "Raw uploaded text stays in the local application environment.",
            "Only redacted text and structured grant facts are eligible for external LLM analysis.",
        ]
        if not external_llm_enabled:
            notes.append("External LLM analysis is off. Results shown are based on local parsing and rules.")
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
