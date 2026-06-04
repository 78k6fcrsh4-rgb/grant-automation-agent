"""Golden-set regression test for full extraction.

Runs the real pipeline (regex base -> LLM enrichment) on the Milton/DuPage
documents and asserts the hand-verified expected values. Marked `integration`
and skipped automatically when no OPENAI_API_KEY is configured, so the offline
suite stays green in CI without a key.
"""
import os
import pytest

from app.models.schemas import PrivacySettings, SourceDocument
from app.services.local_extraction_service import LocalExtractionService
from app.services.llm_service import LLMService

pytestmark = pytest.mark.integration

needs_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY") and os.getenv("DEMO_MODE", "false").lower() != "true",
    reason="OPENAI_API_KEY not set — skipping live extraction test",
)


@needs_key
def test_full_extraction_matches_golden(proposal_text, moa_text, expected):
    merged = f"[PROPOSAL]\n{proposal_text}\n\n[AWARD LETTER]\n{moa_text}"
    base = LocalExtractionService().extract(
        merged,
        source_documents=[SourceDocument(document_type="combined")],
        proposal_text=proposal_text,
        award_letter_text=moa_text,
        privacy_settings=PrivacySettings(),
    )
    out = LLMService().enrich_grant_data(
        base, sanitized_text=merged,
        source_documents=base.source_documents, award_text=moa_text,
    )

    assert out.grant_amount == expected["grant_amount"], \
        f"expected {expected['grant_amount']}, got {out.grant_amount}"
    assert expected["organization_name_contains"] in (out.organization_name or "")
    assert expected["funder_name_contains"] in (out.funder_name or "")
    assert expected["grant_title_contains"].lower() in (out.grant_title or "").lower()
    assert any(tok in (out.grant_period or "") for tok in expected["grant_period_contains_any"])
    assert len(out.reporting_requirements) >= expected["min_reporting_requirements"]
    if out.budget:
        assert out.budget.total_grant_amount == expected["grant_amount"], \
            f"budget total {out.budget.total_grant_amount} != award {expected['grant_amount']}"


def test_regex_only_flags_the_threshold_trap(proposal_text, moa_text):
    """Even with NO LLM, the validator must catch the $20k threshold mistake.

    This guards the safety net itself and runs offline (no key needed).
    """
    merged = f"[PROPOSAL]\n{proposal_text}\n\n[AWARD LETTER]\n{moa_text}"
    base = LocalExtractionService().extract(
        merged,
        source_documents=[SourceDocument(document_type="combined")],
        proposal_text=proposal_text,
        award_letter_text=moa_text,
        privacy_settings=PrivacySettings(),
    )
    svc = LLMService()
    out = svc.validate_only(base, award_text=moa_text, sanitized_text=merged)
    if out.grant_amount == 20000.0:
        assert any("threshold" in f.lower() for f in out.validation_flags), \
            "regex picked $20k but the validator failed to flag it"
