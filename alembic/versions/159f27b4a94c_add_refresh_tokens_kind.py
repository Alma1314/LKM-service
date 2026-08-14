"""add refresh_tokens.kind

Revision ID: 159f27b4a94c
Revises: af84ee47c641
Create Date: 2026-08-11 21:08:19.404987

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '159f27b4a94c'
down_revision: Union[str, Sequence[str], None] = 'af84ee47c641'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema：新增 refresh_tokens.kind（web=前台 Bearer / admin=后台 cookie）。

    用 server_default='web' 为既有行回填默认值；SQLite 在运行时不会自动走 batch，
    必须显式用 op.batch_alter_table（否则 hand-written add_column 不生效但仍会 stamp）。
    """
    with op.batch_alter_table("refresh_tokens") as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.String(length=8), nullable=False, server_default="web"),
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("refresh_tokens") as batch_op:
        batch_op.drop_column("kind")
