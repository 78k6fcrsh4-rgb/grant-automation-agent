from pydantic import BaseModel, Field
from typing import List, Optional, Literal


DocumentKind = Literal["proposal", "award_letter", "combined", "unknown"]


class SourceDocument(BaseModel):
    file_id: Optional[str] = None
    filename: Optional[str] = None
    document_type: DocumentKind = "unknown"


class PrivacySettings(BaseModel):
    redact_names: bool = True
    redact_salaries: bool = True
    redact_contact_details: bool = True
    enable_external_llm: bool = True


class RedactionEntity(BaseModel):
    entity_type: str
    placeholder: str
    original_preview: str
    count: int = 1


class TransmissionPreview(BaseModel):
    external_llm_enabled: bool = False
    raw_characters: int = 0
    redacted_characters: int = 0
    structured_fields_count: int = 0
    excerpt_count: int = 0
    payload_excerpt: str = ""
    notes: List[str] = Field(default_factory=list)


class LocalExtractionSummary(BaseModel):
    grant_amount_candidates: List[str] = Field(default_factory=list)
    date_candidates: List[str] = Field(default_factory=list)
    reporting_clues: List[str] = Field(default_factory=list)
    reimbursement_clues: List[str] = Field(default_factory=list)
    deliverable_clues: List[str] = Field(default_factory=list)
    unresolved_questions: List[str] = Field(default_factory=list)


class TimelineItem(BaseModel):
    date: str = Field(..., description="Due date or deadline")
    amount: Optional[str] = Field(None, description="Money involved, if any")
    description: str = Field(..., description="Brief description of the event")
    category: Optional[str] = Field(None, description="Event category")
    source_document: Optional[DocumentKind] = Field(None, description="Originating document")
    notes: Optional[str] = Field(None, description="Additional instructions or requirements")


class Timeline(BaseModel):
    items: List[TimelineItem] = Field(default_factory=list)


class BudgetItem(BaseModel):
    category: str = Field(..., description="Budget category")
    amount: float = Field(..., description="Dollar amount")
    description: Optional[str] = Field(None, description="Additional details")
    timeline: Optional[str] = Field(None, description="When to spend")


class Budget(BaseModel):
    total_grant_amount: float = Field(default=0.0)
    items: List[BudgetItem] = Field(default_factory=list)


class WorkPlanTask(BaseModel):
    task_name: str = Field(..., description="Name of the task")
    description: str = Field(..., description="Task description")
    start_date: Optional[str] = Field(None, description="Start date")
    end_date: Optional[str] = Field(None, description="End date")
    responsible_party: Optional[str] = Field(None, description="Who is responsible")
    deliverables: Optional[str] = Field(None, description="Expected deliverables")


class WorkPlan(BaseModel):
    project_title: str = Field(default="Project Plan")
    grant_period: str = Field(default="To Be Determined")
    tasks: List[WorkPlanTask] = Field(default_factory=list)


class ReportingRequirement(BaseModel):
    period: Optional[str] = None
    due_date: Optional[str] = None
    description: str = Field(default="")
    required_elements: List[str] = Field(default_factory=list)


class SubmissionRequirement(BaseModel):
    category: str = Field(default="submission")
    due_date: Optional[str] = None
    lead_time_days: int = 7
    next_day_follow_up: bool = True
    instructions: Optional[str] = None


class GrantData(BaseModel):
    organization_name: Optional[str] = None
    grant_title: Optional[str] = None
    grant_amount: Optional[float] = None
    grant_period: Optional[str] = None
    funder_name: Optional[str] = None
    document_type: Optional[DocumentKind] = "unknown"
    source_documents: List[SourceDocument] = Field(default_factory=list)
    proposal_text: Optional[str] = None
    award_letter_text: Optional[str] = None
    redacted_text: Optional[str] = None
    privacy_settings: PrivacySettings = Field(default_factory=PrivacySettings)
    redactions: List[RedactionEntity] = Field(default_factory=list)
    transmission_preview: Optional[TransmissionPreview] = None
    local_extraction_summary: Optional[LocalExtractionSummary] = None
    used_external_llm: bool = False
    timeline: Optional[Timeline] = None
    budget: Optional[Budget] = None
    workplan: Optional[WorkPlan] = None
    reporting_requirements: List[ReportingRequirement] = Field(default_factory=list)
    submission_requirements: List[SubmissionRequirement] = Field(default_factory=list)
    raw_text: str = Field(..., description="Original text")


class UploadResponse(BaseModel):
    success: bool
    message: str
    file_id: str
    filename: str
    document_type: Optional[DocumentKind] = None


class GenerateDocumentsRequest(BaseModel):
    file_id: str
    generate_workplan: bool = True
    generate_budget: bool = True
    generate_report_template: bool = True
    generate_calendar: bool = True
    generate_agenda_template: bool = True
    disbursement_interval_days: int = 30
    disbursement_reminder_days: int = 7
    meeting_interval_days: int = 14


class PackageUploadResponse(BaseModel):
    success: bool
    package_id: str
    message: str
    proposal_file_id: Optional[str] = None
    award_file_id: Optional[str] = None
    proposal_filename: Optional[str] = None
    award_filename: Optional[str] = None
    used_external_llm: bool = False
    redaction_count: int = 0
