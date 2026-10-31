"""symptom threads

Revision ID: edb2cd74fbec
Revises: 876e1ae4c4f8
Create Date: 2026-11-02 21:56:45.185980

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'edb2cd74fbec'
down_revision: Union[str, None] = '876e1ae4c4f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SUMMARYASSESSMENT = postgresql.ENUM("ACCURATE", "CORRECTED", "REJECTED", name="summaryassessment", create_type=False)
MESSAGEAUTHOR = postgresql.ENUM("PATIENT", "CLINICIAN", "AI", "SYSTEM", name="messageauthor", create_type=False)
URGENCY = postgresql.ENUM("ROUTINE", "SOON", "URGENT", "EMERGENCY", name="urgency", create_type=False)
CASEKIND = postgresql.ENUM("REPORT", "SYMPTOM", name="casekind", create_type=False)
DOCUMENTSTATUS = postgresql.ENUM("PROCESSING", "READY", "FAILED", name="documentstatus", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for e in (MESSAGEAUTHOR, URGENCY, CASEKIND, DOCUMENTSTATUS):
        e.create(bind, checkfirst=True)
    for value in ("INTAKE", "TRIAGED", "IN_CONVERSATION"):
        op.execute(f"ALTER TYPE casestatus ADD VALUE IF NOT EXISTS '{value}'")
    op.create_table('dependents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('date_of_birth', sa.Date(), nullable=False),
    sa.Column('relation', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patient_profiles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_dependents_patient_id'), 'dependents', ['patient_id'], unique=False)
    op.create_table('clinician_briefs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('case_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('validation_issues', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('assessment', SUMMARYASSESSMENT, nullable=True),
    sa.Column('correction', sa.Text(), nullable=True),
    sa.Column('model_id', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['medical_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_clinician_briefs_case_id'), 'clinician_briefs', ['case_id'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('case_id', sa.UUID(), nullable=False),
    sa.Column('author_type', MESSAGEAUTHOR, nullable=False),
    sa.Column('author_user_id', sa.UUID(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['medical_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_case_id'), 'messages', ['case_id'], unique=False)
    op.create_table('triage_assessments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('case_id', sa.UUID(), nullable=False),
    sa.Column('message_id', sa.UUID(), nullable=True),
    sa.Column('rule_level', URGENCY, nullable=True),
    sa.Column('rule_flags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('model_level', URGENCY, nullable=True),
    sa.Column('model_flags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('dropped_flags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('final_level', URGENCY, nullable=True),
    sa.Column('model_call_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['medical_cases.id'], ),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_triage_assessments_case_id'), 'triage_assessments', ['case_id'], unique=False)
    op.add_column('agent_executions', sa.Column('document_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_agent_executions_document', 'agent_executions', 'medical_documents', ['document_id'], ['id'])
    op.add_column('clinical_handoffs', sa.Column('triage_id', sa.UUID(), nullable=True))
    op.add_column('clinical_handoffs', sa.Column('ack_due_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clinical_handoffs', sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('clinical_handoffs', 'summary_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.drop_constraint('uq_handoff_consent', 'clinical_handoffs', type_='unique')
    op.create_unique_constraint('uq_handoff_consent_clinician', 'clinical_handoffs', ['consent_id', 'clinician_id'])
    op.create_foreign_key('fk_clinical_handoffs_triage', 'clinical_handoffs', 'triage_assessments', ['triage_id'], ['id'])
    op.add_column('clinician_profiles', sa.Column('on_call', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('clinician_profiles', sa.Column('on_call_priority', sa.Integer(), nullable=False, server_default='100'))
    op.add_column('medical_cases', sa.Column('kind', CASEKIND, nullable=False, server_default='REPORT'))
    op.add_column('medical_cases', sa.Column('subject_dependent_id', sa.UUID(), nullable=True))
    op.add_column('medical_cases', sa.Column('urgency', URGENCY, nullable=True))
    op.add_column('medical_cases', sa.Column('urgency_set_by', sa.String(length=20), nullable=True))
    op.add_column('medical_cases', sa.Column('urgency_baseline_flags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('medical_cases', sa.Column('fallback_advised_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('medical_cases', sa.Column('outcome', sa.String(length=40), nullable=True))
    op.add_column('medical_cases', sa.Column('outcome_note', sa.Text(), nullable=True))
    op.create_foreign_key('fk_medical_cases_dependent', 'medical_cases', 'dependents', ['subject_dependent_id'], ['id'])
    op.add_column('medical_documents', sa.Column('processing_status', DOCUMENTSTATUS, nullable=True))
    op.add_column('patient_consents', sa.Column('audience', sa.String(length=20), nullable=False, server_default='CLINICIAN'))
    op.alter_column('patient_consents', 'clinician_id',
               existing_type=sa.UUID(),
               nullable=True)
    op.add_column('patient_profiles', sa.Column('primary_clinician_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_patient_profiles_primary_clinician', 'patient_profiles', 'clinician_profiles', ['primary_clinician_id'], ['id'])
    op.add_column('users', sa.Column('phone', sa.String(length=30), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'phone')
    op.drop_constraint('fk_patient_profiles_primary_clinician', 'patient_profiles', type_='foreignkey')
    op.drop_column('patient_profiles', 'primary_clinician_id')
    op.alter_column('patient_consents', 'clinician_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('patient_consents', 'audience')
    op.drop_column('medical_documents', 'processing_status')
    op.drop_constraint('fk_medical_cases_dependent', 'medical_cases', type_='foreignkey')
    op.drop_column('medical_cases', 'outcome_note')
    op.drop_column('medical_cases', 'outcome')
    op.drop_column('medical_cases', 'fallback_advised_at')
    op.drop_column('medical_cases', 'urgency_baseline_flags')
    op.drop_column('medical_cases', 'urgency_set_by')
    op.drop_column('medical_cases', 'urgency')
    op.drop_column('medical_cases', 'subject_dependent_id')
    op.drop_column('medical_cases', 'kind')
    op.drop_column('clinician_profiles', 'on_call_priority')
    op.drop_column('clinician_profiles', 'on_call')
    op.drop_constraint('fk_clinical_handoffs_triage', 'clinical_handoffs', type_='foreignkey')
    op.drop_constraint('uq_handoff_consent_clinician', 'clinical_handoffs', type_='unique')
    op.create_unique_constraint('uq_handoff_consent', 'clinical_handoffs', ['consent_id'])
    op.alter_column('clinical_handoffs', 'summary_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('clinical_handoffs', 'escalated_at')
    op.drop_column('clinical_handoffs', 'ack_due_at')
    op.drop_column('clinical_handoffs', 'triage_id')
    op.drop_constraint('fk_agent_executions_document', 'agent_executions', type_='foreignkey')
    op.drop_column('agent_executions', 'document_id')
    op.drop_index(op.f('ix_triage_assessments_case_id'), table_name='triage_assessments')
    op.drop_table('triage_assessments')
    op.drop_index(op.f('ix_messages_case_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_clinician_briefs_case_id'), table_name='clinician_briefs')
    op.drop_table('clinician_briefs')
    op.drop_index(op.f('ix_dependents_patient_id'), table_name='dependents')
    op.drop_table('dependents')
    bind = op.get_bind()
    for e in (DOCUMENTSTATUS, CASEKIND, URGENCY, MESSAGEAUTHOR):
        e.drop(bind, checkfirst=True)
    # Postgres can't drop enum values; INTAKE/TRIAGED/IN_CONVERSATION stay on casestatus.
    # ### end Alembic commands ###
