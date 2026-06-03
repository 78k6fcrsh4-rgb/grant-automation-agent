"""Offline tests for heuristic document classification."""
from app.services.classification import heuristic_classify


def test_moa_classified_as_award(moa_text):
    assert heuristic_classify(moa_text) == "award_letter"


def test_proposal_classified_as_proposal(proposal_text):
    assert heuristic_classify(proposal_text) == "proposal"


def test_combined_marker(proposal_text, moa_text):
    merged = f"[PROPOSAL]\n{proposal_text}\n[AWARD LETTER]\n{moa_text}"
    assert heuristic_classify(merged) == "combined"


def test_empty_is_unknown():
    assert heuristic_classify("") == "unknown"
