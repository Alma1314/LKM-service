"""add projects tables

Revision ID: a1b2c3d4e5f6
Revises: 40d7c7f6e9ca
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '40d7c7f6e9ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('projects',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('summary', sa.String(length=300), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('applicant_id', sa.Integer(), nullable=False),
    sa.Column('is_incubated', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['applicant_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('project_applications',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('applicant_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('summary', sa.String(length=300), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('member_claims', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reviewer_id', sa.Integer(), nullable=True),
    sa.Column('review_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['applicant_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('project_members',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('role_in_project', sa.String(length=100), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('project_members')
    op.drop_table('project_applications')
    op.drop_table('projects')
    # ### end Alembic commands ###
