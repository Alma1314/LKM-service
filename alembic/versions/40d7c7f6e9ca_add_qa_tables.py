"""add qa tables

Revision ID: 40d7c7f6e9ca
Revises: 3f30da473338
Create Date: 2026-08-20 13:37:25.167710

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40d7c7f6e9ca'
down_revision: Union[str, Sequence[str], None] = '3f30da473338'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 循环 FK（qa_questions.accepted_answer_id ⇄ qa_answers）：先建 qa_questions（暂不含
    # accepted_answer_id FK 约束，仅普通可空整数列），再建 qa_answers / qa_question_images，
    # 最后在两张表都就绪后单独 py create_foreign_key（SQLite 不允许创建时引用未存在的表）。
    op.create_table('qa_questions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('situation', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('bounty_people', sa.Integer(), nullable=False),
    sa.Column('bounty_per_person', sa.Integer(), nullable=False),
    sa.Column('bounty_total', sa.Integer(), nullable=False),
    sa.Column('bounty_distributed', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('accepted_answer_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id']),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('qa_answers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('is_accepted', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id']),
    sa.ForeignKeyConstraint(['question_id'], ['qa_questions.id']),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('qa_question_images',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['qa_questions.id']),
    sa.PrimaryKeyConstraint('id')
    )
    # accepted_answer_id FK 须在 qa_answers 建好后追加。SQLite 不能在普通 create_table 内引用
    # 语义上后建的 qa_answers（autogenerate 顺序会引 PostgreSQL 不存在的表），故用 batch 模式
    # 在两张表就绪后再补 FK：PostgreSQL 直接 ALTER，SQLite 走 batch 的 copy-and-move。
    with op.batch_alter_table('qa_questions') as batch_op:
        batch_op.create_foreign_key('fk_qa_questions_accepted_answer', 'qa_answers',
                                    ['accepted_answer_id'], ['id'])
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # 反向：先删 accepted FK / 子表，再删主表；依赖顺序确保无残留约束。
    with op.batch_alter_table('qa_questions') as batch_op:
        batch_op.drop_constraint('fk_qa_questions_accepted_answer', type_='foreignkey')
    op.drop_table('qa_question_images')
    op.drop_table('qa_answers')
    op.drop_table('qa_questions')
    # ### end Alembic commands ###
