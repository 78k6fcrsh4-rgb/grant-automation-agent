export interface SourceDocument {
  file_id?: string;
  filename?: string;
  document_type: 'proposal' | 'award_letter' | 'combined' | 'unknown';
}

export interface PrivacySettings {
  redact_names: boolean;
  redact_salaries: boolean;
  redact_contact_details: boolean;
  enable_external_llm: boolean;
}

export interface RedactionEntity {
  entity_type: string;
  placeholder: string;
  original_preview: string;
  count: number;
}

export interface TransmissionPreview {
  external_llm_enabled: boolean;
  raw_characters: number;
  redacted_characters: number;
  structured_fields_count: number;
  excerpt_count: number;
  payload_excerpt: string;
  notes: string[];
}

export interface LocalExtractionSummary {
  grant_amount_candidates: string[];
  date_candidates: string[];
  reporting_clues: string[];
  reimbursement_clues: string[];
  deliverable_clues: string[];
  unresolved_questions: string[];
}

export interface TimelineItem {
  date: string;
  amount?: string;
  description: string;
  category?: string;
  source_document?: 'proposal' | 'award_letter' | 'combined' | 'unknown';
  notes?: string;
}

export interface Timeline {
  items: TimelineItem[];
}

export interface BudgetItem {
  category: string;
  amount: number;
  description?: string;
  timeline?: string;
}

export interface Budget {
  total_grant_amount: number;
  items: BudgetItem[];
}

export interface WorkPlanTask {
  task_name: string;
  description: string;
  start_date?: string;
  end_date?: string;
  responsible_party?: string;
  deliverables?: string;
}

export interface WorkPlan {
  project_title: string;
  grant_period: string;
  tasks: WorkPlanTask[];
}

export interface ReportingRequirement {
  period?: string;
  due_date?: string;
  description: string;
  required_elements: string[];
}

export interface SubmissionRequirement {
  category: string;
  due_date?: string;
  lead_time_days: number;
  next_day_follow_up: boolean;
  instructions?: string;
}

export interface GrantData {
  organization_name?: string;
  grant_title?: string;
  grant_amount?: number;
  grant_period?: string;
  funder_name?: string;
  document_type?: 'proposal' | 'award_letter' | 'combined' | 'unknown';
  source_documents?: SourceDocument[];
  proposal_text?: string;
  award_letter_text?: string;
  redacted_text?: string;
  privacy_settings: PrivacySettings;
  redactions: RedactionEntity[];
  transmission_preview?: TransmissionPreview;
  local_extraction_summary?: LocalExtractionSummary;
  used_external_llm: boolean;
  timeline?: Timeline;
  budget?: Budget;
  workplan?: WorkPlan;
  reporting_requirements?: ReportingRequirement[];
  submission_requirements?: SubmissionRequirement[];
  raw_text: string;
}

export interface UploadResponse {
  success: boolean;
  message: string;
  file_id: string;
  filename: string;
  document_type?: 'proposal' | 'award_letter' | 'combined' | 'unknown';
}

export interface PackageUploadResponse {
  success: boolean;
  package_id: string;
  message: string;
  proposal_file_id?: string;
  award_file_id?: string;
  proposal_filename?: string;
  award_filename?: string;
  used_external_llm: boolean;
  redaction_count: number;
}

export interface GenerateDocumentsRequest {
  file_id: string;
  generate_workplan?: boolean;
  generate_budget?: boolean;
  generate_report_template?: boolean;
  generate_calendar?: boolean;
  generate_agenda_template?: boolean;
  disbursement_interval_days?: number;
  disbursement_reminder_days?: number;
  meeting_interval_days?: number;
}

export interface GeneratedDocument {
  filename: string;
  download_url: string;
}

export interface GenerateDocumentsResponse {
  success: boolean;
  files: {
    workplan?: GeneratedDocument;
    budget?: GeneratedDocument;
    report?: GeneratedDocument;
    calendar?: GeneratedDocument;
    agenda?: GeneratedDocument;
  };
  calendar_discrepancy?: string[];
}

export interface GrantListItem {
  file_id: string;
  filename: string;
  organization?: string;
  grant_title?: string;
  grant_amount?: number;
  created_at?: string;
  processed: boolean;
}
