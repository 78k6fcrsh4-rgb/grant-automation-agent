"""Offline tests for the deterministic validators. No API key required.

These lock in the single most dangerous failure mode: choosing the $20,000
threshold clause instead of the real $33,600 award.
"""
from app.services import validation


def test_threshold_context_is_detected():
    assert validation.classify_amount_context("for awards of $20,000 or less, only one") == "threshold"


def test_award_context_is_detected():
    assert validation.classify_amount_context("a funding award in the amount of $33,600 for") == "award"


def test_cost_context_is_detected():
    assert validation.classify_amount_context("total project cost of $1,104,807") == "cost"


def test_wrong_threshold_amount_is_flagged(moa_text):
    flags = validation.validate_amount(20000.0, moa_text)
    assert flags, "the $20,000 threshold figure must be flagged"
    assert "threshold" in flags[0].lower()


def test_correct_amount_is_not_flagged(moa_text):
    # $33,600 appears as the real award; it should pass clean.
    assert validation.validate_amount(33600.0, moa_text) == []


def test_short_period_is_flagged():
    flags = validation.validate_period("March 19, 2026 – April 8, 2026")
    assert flags and "days" in flags[0]


def test_fiscal_year_period_is_not_flagged():
    assert validation.validate_period("Fiscal Year 2026") == []


def test_missing_org_is_flagged(moa_text):
    flags = validation.validate_extraction(
        grant_amount=33600.0, grant_period="Fiscal Year 2026",
        organization_name=None, reporting_count=2, award_text=moa_text,
    )
    assert any("organization name" in f.lower() for f in flags)
