export type Role = "PATIENT" | "CLINICIAN" | "ADMIN";

export type CaseStatus =
  | "UPLOADED"
  | "PROCESSING"
  | "SUMMARY_READY"
  | "AWAITING_CONSENT"
  | "CONSENT_GRANTED"
  | "HANDOFF_SENT"
  | "ACKNOWLEDGED"
  | "UNDER_REVIEW"
  | "REVIEW_COMPLETED"
  | "CLOSED"
  | "PROCESSING_FAILED"
  | "NEEDS_CORRECTION"
  | "CONSENT_WITHDRAWN"
  | "HANDOFF_CANCELLED"
  | "INTAKE"
  | "TRIAGED"
  | "IN_CONVERSATION";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  clinician?: { id: string; specialty: string; clinic_name: string; on_call?: boolean; on_call_priority?: number };
  patient?: { id: string; province: string | null };
}

export interface Finding {
  id: string;
  test_name: string;
  value: string;
  unit: string | null;
  reference_range: string | null;
  flag: string | null;
  outside_reference_range: boolean | null;
  report_date: string | null;
  lab_name: string | null;
  source_page: number | null;
  source_text: string | null;
  status: "VERIFIED" | "NEEDS_REVIEW";
  validation_notes: string[];
  extraction_method: string;
}

export interface PatientExplanation {
  overview: string;
  findings: { finding_id: string; plain_language: string }[];
  items_for_clinician_review: { finding_id: string; reason: string }[];
  questions_to_ask: string[];
  limitations: string[];
}

export interface ClinicianSummary {
  headline: string;
  key_findings: {
    finding_id: string;
    test_name: string;
    value: string;
    unit: string | null;
    reference_range: string | null;
    reported_flag: string | null;
    note: string;
  }[];
  other_findings_count: number;
  items_requiring_review: string[];
  data_quality: string[];
  limitations: string[];
}

export interface Summary {
  id: string;
  version: number;
  status: "ACTIVE" | "FAILED_VALIDATION" | "CORRECTED" | "REJECTED";
  provider: string;
  model_id: string;
  created_at: string;
  patient_explanation: PatientExplanation;
  validation_issues: string[];
  clinician_summary?: ClinicianSummary;
  clinician_correction?: string | null;
}

export interface ExecutionStep {
  name?: string;
  type?: "tool_call" | "final" | "limit";
  status?: string;
  tool?: string;
  arguments?: Record<string, unknown>;
  result?: Record<string, unknown>;
  ok?: boolean;
  turn?: number;
  model?: string;
  message?: string;
  duration_ms?: number;
  detail?: Record<string, unknown>;
  error?: string;
}

export interface ModelCall {
  id: string;
  task: string;
  provider: string;
  model_id: string;
  status: string;
  latency_ms: number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  response_id: string | null;
  error: string | null;
  created_at: string;
}

export interface Execution {
  id: string;
  kind: "PROCESSING" | "HANDOFF" | "FOLLOW_UP";
  status: "RUNNING" | "SUCCEEDED" | "FAILED";
  current_step: string | null;
  steps: ExecutionStep[];
  error: string | null;
  started_at: string;
  finished_at: string | null;
  model_calls?: ModelCall[];
  case_id?: string;
}

export interface Handoff {
  id: string;
  status: "SENT" | "ACKNOWLEDGED" | "COMPLETED" | "CANCELLED";
  clinician_name: string;
  clinic_name: string;
  sent_at: string;
  acknowledged_at: string | null;
}

export interface Consent {
  id: string;
  status: "GRANTED" | "WITHDRAWN";
  clinician_name: string;
  scope: string[];
  purpose: string;
  granted_at: string;
  withdrawn_at: string | null;
}

export interface CaseListItem {
  id: string;
  title: string;
  status: CaseStatus;
  patient_name: string;
  document_name: string | null;
  created_at: string;
  updated_at: string;
  handoff: Handoff | null;
}

export interface Task {
  id: string;
  case_id: string;
  kind: string;
  description: string;
  assignee_role: Role;
  status: "OPEN" | "DONE" | "CANCELLED";
  created_by: string;
  due_at: string | null;
  created_at: string;
}

export interface PatientCase extends CaseListItem {
  document: { id: string; filename: string; page_count: number | null; uploaded_at: string } | null;
  findings: Finding[];
  summary: Summary | null;
  consents: Consent[];
  review: { next_step: string | null; patient_message: string | null; completed_at: string | null } | null;
  executions: Execution[];
}

export interface ClinicianCase extends CaseListItem {
  patient: { name: string; date_of_birth: string | null; province: string | null; synthetic_health_ref: string | null };
  document: { id: string; filename: string; page_count: number | null } | null;
  findings: Finding[];
  summary: Summary | null;
  consents: Consent[];
  review: {
    summary_assessment: "ACCURATE" | "CORRECTED" | "REJECTED" | null;
    summary_correction: string | null;
    clinical_notes: string | null;
    next_step: string | null;
    patient_message: string | null;
    started_at: string;
    completed_at: string | null;
  } | null;
  tasks: Task[];
  executions: Execution[];
}

export interface Notification {
  id: string;
  case_id: string | null;
  title: string;
  body: string;
  source: string;
  read: boolean;
  created_at: string;
}

export interface SharingPreview {
  status: CaseStatus;
  scope: { key: string; label: string }[];
  purpose: string;
  clinicians: { id: string; name: string; specialty: string; clinic_name: string }[];
  summary_available: boolean;
  notes: string[];
}

export interface AiStatus {
  provider: string;
  model: string;
  base_url: string;
  api_key_configured: boolean;
  last_successful_meta_call: ModelCall | null;
}

// --- Symptom threads ---------------------------------------------------------------

export type Urgency = "ROUTINE" | "SOON" | "URGENT" | "EMERGENCY";

export interface Dependent {
  id: string;
  name: string;
  date_of_birth: string;
  relation: string;
  age_years: number | null;
}

export interface ThreadQuestion {
  id: string;
  question: string;
  options: string[];
}

export interface ThreadMessage {
  id: string;
  author_type: "PATIENT" | "CLINICIAN" | "AI" | "SYSTEM";
  author_name: string | null;
  body: string;
  payload: ({ kind: string; questions?: ThreadQuestion[]; round?: number; level?: Urgency; document_id?: string; question_id?: string; answer?: string } & Record<string, unknown>) | null;
  created_at: string;
}

export interface ThreadListItem {
  id: string;
  kind: "SYMPTOM" | "REPORT";
  title: string;
  subject_name: string;
  urgency: Urgency | null;
  status: CaseStatus;
  last_message_at: string | null;
  created_at: string;
}

export interface CareTeamMember {
  name: string;
  status: "SENT" | "ACKNOWLEDGED" | "COMPLETED" | "CANCELLED";
  notified_at: string;
  acknowledged_at: string | null;
}

export interface ThreadAttachment {
  id: string;
  filename: string;
  processing_status: "PROCESSING" | "READY" | "FAILED" | null;
  uploaded_at: string;
  findings?: Finding[];
  explanation?: PatientExplanation | null;
}

export interface PatientThread extends ThreadListItem {
  subject: { name: string; relation: string; age_years: number | null; dependent_id: string | null };
  emergency: boolean;
  guidance: string | null;
  emergency_steps: string[];
  worsening_signs: string[];
  care_team: CareTeamMember[];
  messages: ThreadMessage[];
  pending_questions: ThreadQuestion[];
  consent_active: boolean;
  fallback_advised: boolean;
  attachments: ThreadAttachment[];
  outcome: string | null;
}

export interface TriageFlag {
  flag: string;
  patient_quote: string;
}

export interface ClinicianBrief {
  version: number;
  content: {
    headline: string;
    timeline: string[];
    red_flags: TriageFlag[];
    possible_causes: { cause: string; supporting_quotes: string[]; against_quotes: string[]; likelihood: "higher" | "lower" }[];
    suggested_questions: string[];
    suggested_next_steps: string[];
    draft_treatment_idea: string;
    what_ai_told_patient: string[];
  };
  validation_issues: string[];
  assessment: "ACCURATE" | "CORRECTED" | "REJECTED" | null;
  correction: string | null;
  model_id: string;
  created_at: string;
}

export interface TriageAssessmentView {
  rule_level: Urgency | null;
  rule_flags: string[];
  model_level: Urgency | null;
  model_flags: TriageFlag[];
  dropped_flags: TriageFlag[];
  reasons: string[];
  final_level: Urgency | null;
  status: string;
  created_at: string;
}

export interface ClinicianThread extends PatientThread {
  urgency_set_by: string | null;
  patient_name: string;
  patient_phone: string | null;
  my_handoff: { status: string; ack_due_at: string | null; sent_at: string };
  brief: ClinicianBrief | null;
  assessments: TriageAssessmentView[];
  findings: Finding[];
  outcome_note: string | null;
}

export interface QueueRow extends ThreadListItem {
  subject_age_years: number | null;
  patient_name: string;
  ack_due_at: string | null;
  first_message_at: string;
}
