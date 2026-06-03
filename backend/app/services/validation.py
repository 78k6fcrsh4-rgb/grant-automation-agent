"""Deterministic post-extraction validators.

These run AFTER extraction (LLM or regex) and never change values. They only
surface human-readable flags when an extracted value looks suspicious, so a
reviewer can confirm it before documents are generated. This is the safety net
that turns "silently wrong" (e.g. picking a $20,000 threshold clause as the
award) into "visibly questionable".

Everything here is pure and offline-testable — no network, no API key.
"""
import re
from datetime import datetime
from typing import List, Optional, Tuple

_AMOUNT_RE = re.compile(r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\$\s?\d+(?:\.\d{2})?")

# Phrases near a dollar figure that mean it is NOT this grantee's award amount.
_THRESHOLD_CUES = (
    "or less", "or fewer", "or more", "up to", "less than", "no more than",
    "greater than", "at least", "minimum", "maximum", "not to exceed",
    "not exceed", "exceeding", "awards of", "award of $", "for awards",
)
# Phrases meaning the figure is a project/program cost, not the award.
_COST_CUES = (
    "total cost", "total project", "project cost", "program cost",
    "program / project cost", "total program", "cost of", "budget total",
    "total budget", "requested amount of $",
)
# Phrases that positively indicate THIS award's amount.
_AWARD_CUES = (
    "in the amount of", "awarded", "grant in the amount", "funding award",
    "providing", "award amount", "total award", "amount of $",
)

_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")


def to_float(amount_str: str) -> Optional[float]:
    cleaned = re.sub(r"[^\d.]", "", amount_str or "")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def find_amounts_with_context(text: str, window: int = 70) -> List[Tuple[float, str]]:
    """Return (value, surrounding_context_lowercased) for every $ figure."""
    out: List[Tuple[float, str]] = []
    for m in _AMOUNT_RE.finditer(text or ""):
        val = to_float(m.group(0))
        if val is None:
            continue
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        out.append((val, text[start:end].lower()))
    return out


def _any(cues, ctx: str) -> bool:
    return any(c in ctx for c in cues)


def classify_amount_context(ctx: str) -> str:
    """One of: 'threshold', 'cost', 'award', 'other'."""
    if _any(_THRESHOLD_CUES, ctx):
        return "threshold"
    if _any(_COST_CUES, ctx):
        return "cost"
    if _any(_AWARD_CUES, ctx):
        return "award"
    return "other"


def validate_amount(chosen: Optional[float], award_text: str) -> List[str]:
    """Flag a chosen award amount that looks like a threshold/eligibility or
    cost figure rather than the actual award, or that is absent from the text."""
    flags: List[str] = []
    if chosen is None:
        return flags
    amounts = find_amounts_with_context(award_text or "")
    occurrences = [ctx for (val, ctx) in amounts if abs(val - chosen) < 0.01]

    if not occurrences:
        flags.append(
            f"Award amount ${chosen:,.0f} was not found verbatim in the award letter "
            f"text — verify it is correct."
        )
        return flags

    kinds = {classify_amount_context(ctx) for ctx in occurrences}
    if kinds and kinds.issubset({"threshold"}):
        flags.append(
            f"Award amount ${chosen:,.0f} only appears inside a threshold/eligibility "
            f"clause (e.g. \"awards of ${chosen:,.0f} or less\") — this is probably NOT "
            f"the actual award. Confirm the awarded figure."
        )
    elif kinds and kinds.issubset({"cost"}):
        flags.append(
            f"Award amount ${chosen:,.0f} only appears as a project/program cost, not as "
            f"the awarded figure — confirm the award amount."
        )
    return flags


def _parse_dates(text: str) -> List[datetime]:
    dates: List[datetime] = []
    for m in re.finditer(
        r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", text or "", re.IGNORECASE
    ):
        try:
            month = _MONTHS.index(m.group(1).lower()) + 1
            dates.append(datetime(int(m.group(3)), month, int(m.group(2))))
        except (ValueError, IndexError):
            continue
    return dates


def validate_period(period: Optional[str], award_text: str = "") -> List[str]:
    """Flag a grant period that looks like effective→signature dates rather than
    an actual performance period (the classic short-span mistake)."""
    flags: List[str] = []
    if not period:
        return flags
    dates = _parse_dates(period)
    if len(dates) >= 2:
        span = abs((dates[1] - dates[0]).days)
        if span <= 45:
            flags.append(
                f"Grant period \"{period}\" spans only {span} days — this is likely the "
                f"effective and signature dates, not the performance period. Most grant "
                f"terms run a fiscal year. Verify the actual term."
            )
    # If the award names a fiscal year the period should reflect it.
    fy = re.search(r"fiscal year\s+(\d{4})|\bFY\s*'?(\d{2,4})\b", award_text or "", re.IGNORECASE)
    if fy and period:
        yr = fy.group(1) or fy.group(2)
        if yr and yr[-2:] not in period and (yr if len(yr) == 4 else "20" + yr) not in period:
            flags.append(
                f"The award references a fiscal year ({fy.group(0).strip()}) that does not "
                f"appear in the extracted grant period \"{period}\" — confirm the term."
            )
    return flags


def validate_extraction(*, grant_amount: Optional[float], grant_period: Optional[str],
                        organization_name: Optional[str], reporting_count: int,
                        award_text: str = "", full_text: str = "") -> List[str]:
    """Aggregate validator. Returns a list of plain-English review flags."""
    flags: List[str] = []
    flags += validate_amount(grant_amount, award_text or full_text)
    flags += validate_period(grant_period, award_text or full_text)
    if not organization_name:
        flags.append("Awardee / organization name was not extracted — confirm it manually.")
    if reporting_count == 0:
        flags.append("No reporting requirements were extracted — most awards include at "
                     "least one report; verify none were missed.")
    return flags
