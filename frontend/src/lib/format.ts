import type { CaseStatus } from "./types";

export const STATUS_LABEL: Record<CaseStatus, string> = {
  UPLOADED: "Uploaded",
  PROCESSING: "Processing",
  SUMMARY_READY: "Summary ready",
  AWAITING_CONSENT: "Awaiting consent",
  CONSENT_GRANTED: "Consent granted",
  HANDOFF_SENT: "Sent to clinician",
  ACKNOWLEDGED: "Acknowledged",
  UNDER_REVIEW: "Under review",
  REVIEW_COMPLETED: "Review completed",
  CLOSED: "Closed",
  PROCESSING_FAILED: "Processing failed",
  NEEDS_CORRECTION: "Needs correction",
  CONSENT_WITHDRAWN: "Consent withdrawn",
  HANDOFF_CANCELLED: "Handoff cancelled",
};

export type Tone = "neutral" | "info" | "progress" | "success" | "warning" | "danger";

export const STATUS_TONE: Record<CaseStatus, Tone> = {
  UPLOADED: "neutral",
  PROCESSING: "progress",
  SUMMARY_READY: "info",
  AWAITING_CONSENT: "warning",
  CONSENT_GRANTED: "info",
  HANDOFF_SENT: "progress",
  ACKNOWLEDGED: "progress",
  UNDER_REVIEW: "progress",
  REVIEW_COMPLETED: "success",
  CLOSED: "neutral",
  PROCESSING_FAILED: "danger",
  NEEDS_CORRECTION: "danger",
  CONSENT_WITHDRAWN: "warning",
  HANDOFF_CANCELLED: "warning",
};

/** Main path through the workflow, used for the progress tracker. */
export const HAPPY_PATH: CaseStatus[] = [
  "UPLOADED",
  "PROCESSING",
  "SUMMARY_READY",
  "AWAITING_CONSENT",
  "CONSENT_GRANTED",
  "HANDOFF_SENT",
  "ACKNOWLEDGED",
  "UNDER_REVIEW",
  "REVIEW_COMPLETED",
  "CLOSED",
];

export const NEXT_STEP_LABEL: Record<string, string> = {
  NO_FURTHER_ACTION: "No further action needed",
  SCHEDULE_APPOINTMENT: "Schedule a follow-up appointment",
  REPEAT_TEST: "Repeat the laboratory test",
  REFER_TO_SPECIALIST: "Referral to a specialist (prepared for clinician signature)",
  CONTACT_PATIENT: "Clinic will contact you",
};

export const STEP_LABEL: Record<string, string> = {
  document_processing: "Read PDF text",
  deterministic_parse: "Parse result rows",
  meta_report_understanding: "Report understanding",
  finding_validation: "Ground findings in source",
  meta_patient_explanation: "Patient explanation",
  meta_clinician_summary: "Clinician handoff summary",
  output_validation: "Safety & consistency checks",
};

export function formatDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-CA", withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return `${Math.floor(diff / 86400)} d ago`;
}
