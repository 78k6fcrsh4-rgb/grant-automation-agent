"""Document-type classification: proposal vs award letter vs combined.

Used so the app no longer relies solely on which upload field the user picked.
`heuristic_classify` is pure/offline (used as the fallback and in tests); the
LLMService can override it with a model call when available.
"""
import re
from typing import List, Tuple

# Signals that a document is an AWARD / agreement (the authoritative document).
_AWARD_SIGNALS = (
    "memorandum of agreement", "memorandum agreement", "notice of award",
    "award letter", "grant agreement", "this agreement is made",
    "by and between", "hereby agree", "in the amount of", "awardee", "grantee",
    "grantor", "federal award id", "fain", "we are pleased to award",
    "in witness whereof", "indemnification", "governing law", "countersigned",
)
# Signals that a document is a PROPOSAL / application.
_PROPOSAL_SIGNALS = (
    "funding application", "grant application", "application narrative",
    "organization description", "project name", "amount requested",
    "funding amount requested", "character limit", "scope of work",
    "budget narrative", "statement of need", "program area", "population served",
    "project type", "logic model", "proposal", "we are requesting", "mission",
)

DocLabel = str  # "proposal" | "award_letter" | "combined" | "unknown"


def _score(text_lower: str, signals: Tuple[str, ...]) -> Tuple[int, List[str]]:
    hits = [s for s in signals if s in text_lower]
    return len(hits), hits


def heuristic_classify(text: str) -> DocLabel:
    """Best-effort offline classification from keyword signals."""
    if not text or not text.strip():
        return "unknown"
    tl = text.lower()

    # Explicit merged marker produced by the upload pipeline.
    if "[proposal]" in tl and "[award letter]" in tl:
        return "combined"

    award_score, _ = _score(tl, _AWARD_SIGNALS)
    proposal_score, _ = _score(tl, _PROPOSAL_SIGNALS)

    # Both strongly present -> a single combined document.
    if award_score >= 3 and proposal_score >= 3:
        return "combined"
    if award_score == 0 and proposal_score == 0:
        return "unknown"
    if award_score > proposal_score:
        return "award_letter"
    if proposal_score > award_score:
        return "proposal"
    # Tie-break: an executed agreement almost always carries signature/again language.
    if re.search(r"in witness whereof|by and between|hereby agree", tl):
        return "award_letter"
    return "unknown"
