"""add forum_post_likes table

Revision ID: 9c7b2e4f1a3d
Revises: 8f1a2b3c4d5e
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '9c7b2e4f1a3d'
down_revision: Union[str, Sequence[str], None] = '8f1a2b3c4d5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "forum_post_likes",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column(
            "post_id", sa.Integer(), sa.ForeignKey("forum_posts.id"), primary_key=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("forum_post_likes")
