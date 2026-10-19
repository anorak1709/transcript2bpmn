"""speaker roles, dismissed gaps, policy documents, sign-off links

Revision ID: a7c3e1d9b204
Revises: 5b41e0a34c4f
Create Date: 2026-10-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c3e1d9b204'
down_revision: Union[str, Sequence[str], None] = '5b41e0a34c4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('speaker_roles', sa.JSON(), server_default='{}', nullable=False))
    op.add_column('projects', sa.Column('dismissed_gaps', sa.JSON(), server_default='[]', nullable=False))
    op.add_column('transcripts', sa.Column('purpose', sa.String(length=16), server_default='meeting', nullable=False))
    op.add_column('conflicts', sa.Column('origin', sa.String(length=16), server_default='meeting', nullable=False))
    op.create_table(
        'signoffs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('lane_ids', sa.JSON(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('requested_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision', sa.String(length=32), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('decided_version', sa.Integer(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='signoffs_organization_id_fkey'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name='signoffs_project_id_fkey'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_signoffs_organization_id', 'signoffs', ['organization_id'])
    op.create_index('ix_signoffs_project_id', 'signoffs', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_signoffs_project_id', table_name='signoffs')
    op.drop_index('ix_signoffs_organization_id', table_name='signoffs')
    op.drop_table('signoffs')
    op.drop_column('conflicts', 'origin')
    op.drop_column('transcripts', 'purpose')
    op.drop_column('projects', 'dismissed_gaps')
    op.drop_column('projects', 'speaker_roles')
