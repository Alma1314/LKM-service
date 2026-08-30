"""add qa table indexes

Revision ID: b2c3d4e5f60b
Revises: b2c3d4e5f60a
Create Date: 2026-08-30 00:45:00

问答三表此前除主键外无任何索引；按 category 拉列表、按 question_id 拉回答均全表扫。
补充覆盖查询路径的索引。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f60b"
down_revision: str | Sequence[str] | None = "b2c3d4e5f60a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_qa_question_category_id", "qa_questions", ["category", "id"]
    )
    op.create_index(
        "ix_qa_question_status_id", "qa_questions", ["status", "id"]
    )
    op.create_index("ix_qa_answer_question", "qa_answers", ["question_id"])
    op.create_index(
        "ix_qa_answer_question_accepted",
        "qa_answers",
        ["question_id", "is_accepted"],
    )
    op.create_index(
        "ix_qa_question_image_question", "qa_question_images", ["question_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_qa_question_image_question", table_name="qa_question_images")
    op.drop_index("ix_qa_answer_question_accepted", table_name="qa_answers")
    op.drop_index("ix_qa_answer_question", table_name="qa_answers")
    op.drop_index("ix_qa_question_status_id", table_name="qa_questions")
    op.drop_index("ix_qa_question_category_id", table_name="qa_questions")
