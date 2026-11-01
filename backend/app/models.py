import enum
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _enum(e: type[enum.Enum]) -> Enum:
    return Enum(e, name=e.__name__.lower(), values_callable=lambda x: [m.value for m in x])


class UserRole(str, enum.Enum):
    PATIENT = "PATIENT"
    CLINICIAN = "CLINICIAN"
    ADMIN = "ADMIN"


class CaseStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    SUMMARY_READY = "SUMMARY_READY"
    AWAITING_CONSENT = "AWAITING_CONSENT"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    HANDOFF_SENT = "HANDOFF_SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"
    CLOSED = "CLOSED"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"
    CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"
    HANDOFF_CANCELLED = "HANDOFF_CANCELLED"
    # Symptom threads
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    IN_CONVERSATION = "IN_CONVERSATION"


class CaseKind(str, enum.Enum):
    REPORT = "REPORT"
    SYMPTOM = "SYMPTOM"


class Urgency(str, enum.Enum):
    ROUTINE = "ROUTINE"
    SOON = "SOON"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


URGENCY_RANK: dict[Urgency, int] = {Urgency.ROUTINE: 0, Urgency.SOON: 1, Urgency.URGENT: 2, Urgency.EMERGENCY: 3}


def max_urgency(*levels: "Urgency | None") -> "Urgency | None":
    present = [lv for lv in levels if lv is not None]
    return max(present, key=URGENCY_RANK.__getitem__) if present else None


class MessageAuthor(str, enum.Enum):
    PATIENT = "PATIENT"
    CLINICIAN = "CLINICIAN"
    AI = "AI"
    SYSTEM = "SYSTEM"


class DocumentStatus(str, enum.Enum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class ThreadOutcome(str, enum.Enum):
    ADVICE_GIVEN = "ADVICE_GIVEN"
    SEEN_IN_PERSON = "SEEN_IN_PERSON"
    SENT_TO_EMERGENCY = "SENT_TO_EMERGENCY"


class FindingStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class SummaryStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"


class ConsentStatus(str, enum.Enum):
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"


class HandoffStatus(str, enum.Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SummaryAssessment(str, enum.Enum):
    ACCURATE = "ACCURATE"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"


class NextStep(str, enum.Enum):
    NO_FURTHER_ACTION = "NO_FURTHER_ACTION"
    SCHEDULE_APPOINTMENT = "SCHEDULE_APPOINTMENT"
    REPEAT_TEST = "REPEAT_TEST"
    REFER_TO_SPECIALIST = "REFER_TO_SPECIALIST"
    CONTACT_PATIENT = "CONTACT_PATIENT"


class TaskStatus(str, enum.Enum):
    OPEN = "OPEN"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class ExecutionStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on logout so previously issued JWTs stop validating.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    phone: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient_profile: Mapped["PatientProfile | None"] = relationship(back_populates="user")
    clinician_profile: Mapped["ClinicianProfile | None"] = relationship(back_populates="user")


class PatientProfile(Base):
    __tablename__ = "patient_profiles"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    province: Mapped[str | None] = mapped_column(String(50))
    # Fabricated identifier for demo records.
    synthetic_health_ref: Mapped[str | None] = mapped_column(String(50))
    # Family doctor: paged first for this patient's symptom threads.
    primary_clinician_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinician_profiles.id"))
    user: Mapped[User] = relationship(back_populates="patient_profile")
    dependents: Mapped[list["Dependent"]] = relationship(back_populates="patient", order_by="Dependent.date_of_birth")


class Dependent(Base):
    """Someone a patient may open a thread for, e.g. their child."""

    __tablename__ = "dependents"
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[date] = mapped_column(Date)
    relation: Mapped[str] = mapped_column(String(50))  # e.g. daughter
    patient: Mapped[PatientProfile] = relationship(back_populates="dependents")


class ClinicianProfile(Base):
    __tablename__ = "clinician_profiles"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    specialty: Mapped[str] = mapped_column(String(100))
    clinic_name: Mapped[str] = mapped_column(String(200))
    synthetic_license_ref: Mapped[str | None] = mapped_column(String(50))
    on_call: Mapped[bool] = mapped_column(Boolean, default=False)
    # Lower is paged first among on-call clinicians.
    on_call_priority: Mapped[int] = mapped_column(Integer, default=100)
    user: Mapped[User] = relationship(back_populates="clinician_profile")


class MedicalCase(Base):
    __tablename__ = "medical_cases"
    __table_args__ = (Index("ix_cases_org_status", "org_id", "status"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[CaseStatus] = mapped_column(_enum(CaseStatus), default=CaseStatus.UPLOADED)
    kind: Mapped[CaseKind] = mapped_column(_enum(CaseKind), default=CaseKind.REPORT)
    subject_dependent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dependents.id"))
    urgency: Mapped[Urgency | None] = mapped_column(_enum(Urgency))
    urgency_set_by: Mapped[str | None] = mapped_column(String(20))  # rules, model, clinician, fallback
    # Red flags already accounted for when a clinician set the urgency; only new ones may raise it again.
    urgency_baseline_flags: Mapped[list[str]] = mapped_column(JsonType, default=list)
    fallback_advised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(40))
    outcome_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    patient: Mapped[PatientProfile] = relationship()
    documents: Mapped[list["MedicalDocument"]] = relationship(back_populates="case", order_by="MedicalDocument.uploaded_at")
    findings: Mapped[list["ExtractedFinding"]] = relationship(back_populates="case", order_by="ExtractedFinding.position")
    summaries: Mapped[list["AISummary"]] = relationship(back_populates="case", order_by="AISummary.version")
    consents: Mapped[list["PatientConsent"]] = relationship(back_populates="case", order_by="PatientConsent.granted_at")
    handoffs: Mapped[list["ClinicalHandoff"]] = relationship(back_populates="case", order_by="ClinicalHandoff.sent_at")
    reviews: Mapped[list["ClinicalReview"]] = relationship(back_populates="case")
    tasks: Mapped[list["FollowUpTask"]] = relationship(back_populates="case", order_by="FollowUpTask.created_at")
    subject_dependent: Mapped["Dependent | None"] = relationship()
    messages: Mapped[list["Message"]] = relationship(back_populates="case", order_by="Message.created_at")
    triage_assessments: Mapped[list["TriageAssessment"]] = relationship(back_populates="case", order_by="TriageAssessment.created_at")
    briefs: Mapped[list["ClinicianBrief"]] = relationship(back_populates="case", order_by="ClinicianBrief.version")


class MedicalDocument(Base):
    __tablename__ = "medical_documents"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    # Set only for reports attached to a symptom thread; standalone reports track progress on the case status.
    processing_status: Mapped[DocumentStatus | None] = mapped_column(_enum(DocumentStatus))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[MedicalCase] = relationship(back_populates="documents")


class ExtractedFinding(Base):
    __tablename__ = "extracted_findings"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_documents.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    test_name: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(String(100))  # exact string as printed
    unit: Mapped[str | None] = mapped_column(String(50))
    reference_range: Mapped[str | None] = mapped_column(String(100))
    flag: Mapped[str | None] = mapped_column(String(20))  # as reported by the lab (H, L, ...)
    report_date: Mapped[str | None] = mapped_column(String(40))
    lab_name: Mapped[str | None] = mapped_column(String(200))
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[FindingStatus] = mapped_column(_enum(FindingStatus))
    validation_notes: Mapped[list[str]] = mapped_column(JsonType, default=list)
    extraction_method: Mapped[str] = mapped_column(String(40))  # deterministic+meta, meta-only, ...
    case: Mapped[MedicalCase] = relationship(back_populates="findings")


class AISummary(Base):
    __tablename__ = "ai_summaries"
    __table_args__ = (UniqueConstraint("case_id", "version"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[SummaryStatus] = mapped_column(_enum(SummaryStatus))
    patient_explanation: Mapped[dict[str, Any]] = mapped_column(JsonType)
    clinician_summary: Mapped[dict[str, Any]] = mapped_column(JsonType)
    validation_issues: Mapped[list[str]] = mapped_column(JsonType, default=list)
    provider: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(100))
    clinician_correction: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[MedicalCase] = relationship(back_populates="summaries")


class PatientConsent(Base):
    __tablename__ = "patient_consents"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id"))
    # None for care-team consent (symptom threads), which covers every clinician paged on the case.
    clinician_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinician_profiles.id"))
    audience: Mapped[str] = mapped_column(String(20), default="CLINICIAN")  # CLINICIAN, CARE_TEAM
    scope: Mapped[list[str]] = mapped_column(JsonType)
    purpose: Mapped[str] = mapped_column(Text)
    status: Mapped[ConsentStatus] = mapped_column(_enum(ConsentStatus))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    case: Mapped[MedicalCase] = relationship(back_populates="consents")
    clinician: Mapped[ClinicianProfile] = relationship()


class ClinicalHandoff(Base):
    __tablename__ = "clinical_handoffs"
    # One handoff per consent and clinician: duplicate requests can't create duplicate referrals.
    __table_args__ = (UniqueConstraint("consent_id", "clinician_id", name="uq_handoff_consent_clinician"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    consent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_consents.id"))
    clinician_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinician_profiles.id"), index=True)
    summary_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_summaries.id"))
    triage_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("triage_assessments.id"))
    status: Mapped[HandoffStatus] = mapped_column(_enum(HandoffStatus))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    case: Mapped[MedicalCase] = relationship(back_populates="handoffs")
    clinician: Mapped[ClinicianProfile] = relationship()


class ClinicalReview(Base):
    __tablename__ = "clinical_reviews"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    handoff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical_handoffs.id"), unique=True)
    clinician_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinician_profiles.id"))
    summary_assessment: Mapped[SummaryAssessment | None] = mapped_column(_enum(SummaryAssessment))
    summary_correction: Mapped[str | None] = mapped_column(Text)
    clinical_notes: Mapped[str | None] = mapped_column(Text)
    next_step: Mapped[NextStep | None] = mapped_column(_enum(NextStep))
    patient_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    case: Mapped[MedicalCase] = relationship(back_populates="reviews")


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    assignee_role: Mapped[UserRole] = mapped_column(_enum(UserRole))
    status: Mapped[TaskStatus] = mapped_column(_enum(TaskStatus), default=TaskStatus.OPEN)
    created_by: Mapped[str] = mapped_column(String(60))  # "agent", "system", or a user id
    # Prevents the agent from opening the same reminder twice.
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    case: Mapped[MedicalCase] = relationship(back_populates="tasks")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("medical_cases.id"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)  # administrative only, never medical details
    source: Mapped[str] = mapped_column(String(40), default="system")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_resource", "resource_type", "resource_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_type: Mapped[str] = mapped_column(String(20))  # USER, AGENT, SYSTEM
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # PROCESSING, HANDOFF, FOLLOW_UP
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("medical_documents.id"))
    status: Mapped[ExecutionStatus] = mapped_column(_enum(ExecutionStatus))
    current_step: Mapped[str | None] = mapped_column(String(60))
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelCall(Base):
    """One row per LLM inference: proves which model ran, how long it took, and what it cost."""

    __tablename__ = "model_calls"
    id: Mapped[uuid.UUID] = uuid_pk()
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_executions.id"), index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    task: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))  # ok, error, invalid_output
    latency_ms: Mapped[float] = mapped_column(Float)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    response_id: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    author_type: Mapped[MessageAuthor] = mapped_column(_enum(MessageAuthor))
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    # Structured content: questions, answers, guidance, report attachments, system events.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[MedicalCase] = relationship(back_populates="messages")
    author: Mapped[User | None] = relationship()


class TriageAssessment(Base):
    """One urgency evaluation: what the rules found, what the model said, and the level that resulted."""

    __tablename__ = "triage_assessments"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id"))
    rule_level: Mapped[Urgency | None] = mapped_column(_enum(Urgency))
    rule_flags: Mapped[list[str]] = mapped_column(JsonType, default=list)
    model_level: Mapped[Urgency | None] = mapped_column(_enum(Urgency))
    model_flags: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    dropped_flags: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    reasons: Mapped[list[str]] = mapped_column(JsonType, default=list)
    final_level: Mapped[Urgency | None] = mapped_column(_enum(Urgency))
    model_call_ids: Mapped[list[str]] = mapped_column(JsonType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="rules_only")  # rules_only, complete, model_failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[MedicalCase] = relationship(back_populates="triage_assessments")


class ClinicianBrief(Base):
    """Meta-drafted, clinician-only brief for a symptom thread. Never shown to the patient."""

    __tablename__ = "clinician_briefs"
    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medical_cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JsonType)
    validation_issues: Mapped[list[str]] = mapped_column(JsonType, default=list)
    assessment: Mapped[SummaryAssessment | None] = mapped_column(_enum(SummaryAssessment))
    correction: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[MedicalCase] = relationship(back_populates="briefs")
