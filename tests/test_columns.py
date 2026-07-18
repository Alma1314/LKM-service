import sqlite3

import pytest

from app.core.err import BizError, ErrCode
from app.db.init_db import init_db
from app.modules.auth.schemas import UserRegInfo
from app.modules.auth.service import register
from app.modules.columns.models import ColumnApplicationStatus
from app.modules.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationReview,
    ColumnPostCreate,
)
from app.modules.columns.service import (
    create_application,
    create_post,
    get_application,
    get_column,
    get_post,
    list_applications,
    list_columns,
    list_posts,
    review_application,
)


# 使用内存数据库，让每个测试都从干净表结构开始。
# 这样测试不会依赖本地开发库 lkm.db。
@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


# 当前还没有请求头身份校验，所以 columns 测试先显式传 user_id。
def _user(conn, username="alice", email="alice@example.com"):
    return register(conn, UserRegInfo(username=username, email=email, password="secret123"))


# 构造一个待审核的专栏申请，复用正常申请流程。
def _application(conn, user_id=1):
    return create_application(
        conn,
        ColumnApplicationCreate(
            user_id=user_id,
            title="数学思维训练",
            description="面向高中生的数学思维和解题方法专栏。",
            reason="希望长期整理数学学习笔记。",
        ),
    )


# 审核通过后应当为申请创建且只创建一个 active 专栏。
def _approved_column(conn, user_id=1):
    application = _application(conn, user_id=user_id)
    result = review_application(
        conn,
        application.id,
        ColumnApplicationReview(
            reviewer_id=user_id,
            status=ColumnApplicationStatus.APPROVED,
            review_note="方向明确，允许开设。",
        ),
    )
    return result["column"]


# 文章必须隶属于某个专栏，因此测试 helper 始终传入 column_id。
def _post(conn, column_id=1, author_id=1):
    return create_post(
        conn,
        column_id,
        ColumnPostCreate(
            author_id=author_id,
            title="如何建立函数思想",
            summary="从变量关系和图像理解入门函数思想。",
            content="函数思想的核心，是用变化关系理解问题。",
        ),
    )


class TestColumnApplications:
    # 创建申请是专栏业务流程的第一步。
    def should_create_application(self, conn):
        user_id = _user(conn)

        application = _application(conn, user_id=user_id)

        assert application.id == 1
        assert application.user_id == user_id
        assert application.status == ColumnApplicationStatus.PENDING

    def should_list_applications(self, conn):
        user_id = _user(conn)
        _application(conn, user_id=user_id)

        applications = list_applications(conn)

        assert len(applications) == 1
        assert applications[0].title == "数学思维训练"

    def should_get_application(self, conn):
        user_id = _user(conn)
        application = _application(conn, user_id=user_id)

        found = get_application(conn, application.id)

        assert found.id == application.id

    def should_reject_nonexistent_application(self, conn):
        with pytest.raises(BizError) as exc:
            get_application(conn, 999)

        assert exc.value.errcode == ErrCode.COLUMN_APPLICATION_NOT_FOUND


class TestColumnReview:
    # 最小审核流程：只有审核通过后才真正生成专栏。
    def should_create_column_when_application_is_approved(self, conn):
        user_id = _user(conn)
        application = _application(conn, user_id=user_id)

        result = review_application(
            conn,
            application.id,
            ColumnApplicationReview(
                reviewer_id=user_id,
                status=ColumnApplicationStatus.APPROVED,
            ),
        )

        assert result["application"]["status"] == ColumnApplicationStatus.APPROVED
        assert result["column"]["id"] == 1
        assert result["column"]["owner_id"] == user_id
        assert result["column"]["application_id"] == application.id

    def should_not_create_column_when_application_is_rejected(self, conn):
        user_id = _user(conn)
        application = _application(conn, user_id=user_id)

        result = review_application(
            conn,
            application.id,
            ColumnApplicationReview(
                reviewer_id=user_id,
                status=ColumnApplicationStatus.REJECTED,
                review_note="内容方向还不够清晰。",
            ),
        )

        assert result["application"]["status"] == ColumnApplicationStatus.REJECTED
        assert result["column"] is None
        assert list_columns(conn) == []

    def should_not_duplicate_column_when_approving_twice(self, conn):
        user_id = _user(conn)
        application = _application(conn, user_id=user_id)
        review = ColumnApplicationReview(
            reviewer_id=user_id,
            status=ColumnApplicationStatus.APPROVED,
        )

        first = review_application(conn, application.id, review)
        second = review_application(conn, application.id, review)

        assert first["column"]["id"] == second["column"]["id"]
        assert len(list_columns(conn)) == 1


class TestColumns:
    def should_list_columns(self, conn):
        user_id = _user(conn)
        _approved_column(conn, user_id=user_id)

        columns = list_columns(conn)

        assert len(columns) == 1
        assert columns[0].title == "数学思维训练"

    def should_get_column(self, conn):
        user_id = _user(conn)
        column = _approved_column(conn, user_id=user_id)

        found = get_column(conn, column["id"])

        assert found.id == column["id"]

    def should_reject_nonexistent_column(self, conn):
        with pytest.raises(BizError) as exc:
            get_column(conn, 999)

        assert exc.value.errcode == ErrCode.COLUMN_NOT_FOUND


class TestColumnPosts:
    # 文章只能发布到已经存在的专栏下。
    def should_create_post(self, conn):
        user_id = _user(conn)
        column = _approved_column(conn, user_id=user_id)

        post = _post(conn, column_id=column["id"], author_id=user_id)

        assert post.id == 1
        assert post.column_id == column["id"]
        assert post.author_id == user_id
        assert post.status == "published"

    def should_list_posts_under_column(self, conn):
        user_id = _user(conn)
        column = _approved_column(conn, user_id=user_id)
        _post(conn, column_id=column["id"], author_id=user_id)

        posts = list_posts(conn, column["id"])

        assert len(posts) == 1
        assert posts[0].title == "如何建立函数思想"

    def should_get_post_with_column_scope(self, conn):
        user_id = _user(conn)
        column = _approved_column(conn, user_id=user_id)
        post = _post(conn, column_id=column["id"], author_id=user_id)

        found = get_post(conn, post.id, column_id=column["id"])

        assert found.id == post.id

    def should_reject_post_from_wrong_column_scope(self, conn):
        user_id = _user(conn)
        column = _approved_column(conn, user_id=user_id)
        post = _post(conn, column_id=column["id"], author_id=user_id)

        with pytest.raises(BizError) as exc:
            get_post(conn, post.id, column_id=999)

        assert exc.value.errcode == ErrCode.COLUMN_POST_NOT_FOUND

    def should_reject_post_for_nonexistent_column(self, conn):
        user_id = _user(conn)

        with pytest.raises(BizError) as exc:
            _post(conn, column_id=999, author_id=user_id)

        assert exc.value.errcode == ErrCode.COLUMN_NOT_FOUND

def should_test():
    pass