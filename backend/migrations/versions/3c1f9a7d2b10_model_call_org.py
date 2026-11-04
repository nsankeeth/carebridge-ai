"""model calls can belong to an org without a case

Revision ID: 3c1f9a7d2b10
Revises: edb2cd74fbec
Create Date: 2026-11-04 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3c1f9a7d2b10'
down_revision: Union[str, None] = 'edb2cd74fbec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('model_calls', sa.Column('org_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_model_calls_org_id'), 'model_calls', ['org_id'], unique=False)
    op.create_foreign_key('model_calls_org_id_fkey', 'model_calls', 'organizations', ['org_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('model_calls_org_id_fkey', 'model_calls', type_='foreignkey')
    op.drop_index(op.f('ix_model_calls_org_id'), table_name='model_calls')
    op.drop_column('model_calls', 'org_id')
