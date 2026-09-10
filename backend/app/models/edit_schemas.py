"""Request models for the review-and-correct step.

`extra="forbid"` is doing real work here: it means a client physically
cannot PATCH raw_text, redacted_text or any other document field onto a
grant. The whitelist in grant_persistence stops those reaching the
database; this stops them reaching the working copy from outside.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.models.schemas import (
    Budget, ReportingRequirement, SubmissionRequirement, Timeline, WorkPlan,
)

EDITABLE_SCALARS = (
    "organization_name", "funder_name", "grant_title",
    "purpose", "grant_amount", "grant_period",
)


class GrantDataPatch(BaseModel):
    """A partial correction. Omitted fields are left alone; a list that IS
    supplied replaces its counterpart wholesale, because the review page
    edits lists as a unit."""

    model_config = ConfigDict(extra="forbid")

    organization_name: Optional[str] = None
    funder_name: Optional[str] = None
    grant_title: Optional[str] = None
    purpose: Optional[str] = None
    grant_amount: Optional[float] = None
    grant_period: Optional[str] = None

    reporting_requirements: Optional[List[ReportingRequirement]] = None
    submission_requirements: Optional[List[SubmissionRequirement]] = None
    timeline: Optional[Timeline] = None
    budget: Optional[Budget] = None
    workplan: Optional[WorkPlan] = None


class ConfirmResponse(BaseModel):
    success: bool
    mode: str
    filed: bool
    grant_id: Optional[str] = None
    message: str
