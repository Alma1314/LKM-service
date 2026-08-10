import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.modules.auth.models  # pyright: ignore[reportUnusedImport]
from app.core.err import BizError, ErrCode
from app.db.models import Base, ForumPost, Profile, User
from app.db.session import get_session
from app.main import app
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.forum.schemas import CommentCreate, PostCreate
from app.modules.forum.service import (
    create_comment,
    create_post,
    delete_post,
    get_post,
    like_post,
    list_comments,
    list_posts,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal: sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_session():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _user(db, username="alice", email="alice@example.com", nickname=None):
    user = User(
        username=username,
        email=email,
        hashed_password=hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, nickname=nickname))
    db.flush()
    return user.id


def _post(db, author_id=1, title="如何学习微积分", category_id="math", tags=("数学", "微积分")):
    return create_post(
        db,
        author_id,
        PostCreate(
            title=title,
            content="<p>微积分是理解变化与积累的工具，先从极限开始。</p>",
            category_id=category_id,
            tags=list(tags),
        ),
    )


def _comment(db, post_id=1, user_id=1, content="写得不错", parent_id=None):
    return create_comment(
        db,
        post_id,
        user_id,
        CommentCreate(content=content, parent_id=parent_id),
    )


class TestForumPosts:
    def should_create_post_with_nickname_and_excerpt(self, db):
        user_id = _user(db, nickname="爱丽丝")

        post = _post(db, author_id=user_id)

        assert post.id == 1
        assert post.author_id == user_id
        assert post.author_name == "爱丽丝"
        assert post.tags == ["数学", "微积分"]
        assert post.excerpt.startswith("微积分是理解变化")

    def should_use_username_when_no_nickname(self, db):
        user_id = _user(db, username="bob", email="bob@example.com")

        post = _post(db, author_id=user_id)

        assert post.author_name == "bob"

    def should_list_posts_paginated(self, db):
        user_id = _user(db)
        _post(db, author_id=user_id, title="帖子一")
        _post(db, author_id=user_id, title="帖子二")

        page = list_posts(db, page=1, limit=1)

        assert page.total == 2
        assert page.pages == 2
        assert len(page.items) == 1
        assert page.items[0].title == "帖子二"

    def should_filter_posts_by_category(self, db):
        user_id = _user(db)
        _post(db, author_id=user_id, category_id="math")
        _post(db, author_id=user_id, title="物理题", category_id="physics")

        page = list_posts(db, category_id="math")

        assert page.total == 1
        assert page.items[0].category_id == "math"

    def should_get_post_and_bump_view(self, db):
        user_id = _user(db)
        post = _post(db, author_id=user_id)

        first = get_post(db, post.id, bump_view=True)
        second = get_post(db, post.id, bump_view=True)

        assert first.view_count == 1
        assert second.view_count == 2

    def should_reject_nonexistent_post(self, db):
        with pytest.raises(BizError) as exc:
            get_post(db, 999)

        assert exc.value.errcode == ErrCode.FORUM_POST_NOT_FOUND

    def should_delete_own_post(self, db):
        user_id = _user(db)
        post = _post(db, author_id=user_id)

        delete_post(db, post.id, user_id)

        try:
            found = get_post(db, post.id)
        except BizError as exc:
            assert exc.errcode == ErrCode.FORUM_POST_NOT_FOUND
            return
        raise AssertionError(f"expected BizError, got post {found.id} (view={found.view_count})")

    def should_reject_delete_of_others_post(self, db):
        author = _user(db)
        other = _user(db, username="mallory", email="mallory@example.com")
        post = _post(db, author_id=author)

        with pytest.raises(BizError) as exc:
            delete_post(db, post.id, other)

        assert exc.value.errcode == ErrCode.FORBIDDEN

    def should_increment_like(self, db):
        user_id = _user(db)
        post = _post(db, author_id=user_id)

        assert like_post(db, post.id) == 1
        assert like_post(db, post.id) == 2


class TestForumComments:
    def should_create_comment_with_floor(self, db):
        user_id = _user(db)
        post = _post(db, author_id=user_id)

        first = _comment(db, post_id=post.id, user_id=user_id, content="一楼")
        second = _comment(db, post_id=post.id, user_id=user_id, content="二楼")

        assert first.floor_number == 1
        assert second.floor_number == 2
        assert get_post(db, post.id).comment_count == 2

    def should_reject_comment_for_nonexistent_post(self, db):
        user_id = _user(db)

        with pytest.raises(BizError) as exc:
            _comment(db, post_id=999, user_id=user_id)

        assert exc.value.errcode == ErrCode.FORUM_POST_NOT_FOUND

    def should_reject_reply_to_comment_of_another_post(self, db):
        user_id = _user(db)
        post = _post(db, author_id=user_id)
        other = _post(db, author_id=user_id, title="另一个帖子")
        parent = _comment(db, post_id=post.id, user_id=user_id)

        with pytest.raises(BizError) as exc:
            _comment(db, post_id=other.id, user_id=user_id, parent_id=parent.id)

        assert exc.value.errcode == ErrCode.FORUM_COMMENT_NOT_FOUND

    def should_list_comments_ordered_by_floor(self, db):
        user_id = _user(db)
        post = _post(db, author_id=user_id)
        _comment(db, post_id=post.id, user_id=user_id, content="一楼")
        _comment(db, post_id=post.id, user_id=user_id, content="二楼")

        page = list_comments(db, post.id)

        assert page.total == 2
        assert [c.floor_number for c in page.items] == [1, 2]


class TestForumRoutes:
    def _setup_user(self, db, username="tester", email="tester@example.com"):
        user_id = _user(db, username=username, email=email)
        token = create_access_token(user_id=user_id, account_level="normal", role="member")
        return user_id, token

    def should_reject_create_post_without_auth(self, client, db):
        self._setup_user(db)
        resp = client.post(
            "/api/v1/forum/posts",
            json={"title": "标题", "content": "正文", "category_id": "math", "tags": []},
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == 1005

    def should_create_post_with_token(self, client, db):
        user_id, token = self._setup_user(db)
        resp = client.post(
            "/api/v1/forum/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "标题", "content": "正文", "category_id": "math", "tags": ["数学"]},
        )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["author_id"] == user_id

    def should_list_posts_publicly(self, client, db):
        user_id, token = self._setup_user(db)
        client.post(
            "/api/v1/forum/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "公开帖", "content": "正文", "category_id": "math"},
        )

        resp = client.get("/api/v1/forum/posts")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["title"] == "公开帖"

    def should_delete_own_post_through_api(self, client, db):
        user_id, token = self._setup_user(db)
        created = client.post(
            "/api/v1/forum/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "待删除", "content": "正文", "category_id": "math"},
        ).json()["data"]
        post_id = created["id"]

        resp = client.delete(
            f"/api/v1/forum/posts/{post_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        assert client.get(f"/api/v1/forum/posts/{post_id}").json()["code"] == 4001


class TestForumGraphQL:
    """论坛 GraphQL 查询契约测试（对齐前端 queries.ts）。"""

    def _run(self, client, query, variables):
        resp = client.post("/graphql", json={"query": query, "variables": variables})
        assert resp.status_code == 200
        body = resp.json()
        assert "errors" not in body, body.get("errors")
        return body["data"]

    def should_query_posts_with_author(self, client, db):
        user_id = _user(db, username="alice", nickname="爱丽丝")
        post = _post(db, author_id=user_id, title="如何学习微积分", category_id="math")

        data = self._run(
            client,
            """
            query PostList($categoryId: ID, $page: Int!, $pageSize: Int!) {
              posts(categoryId: $categoryId, page: $page, pageSize: $pageSize) {
                total
                items {
                  id title excerpt categoryId tags isPinned isFeatured
                  viewCount likeCount commentCount createdAt
                  author { id displayName avatar username }
                }
              }
            }
            """,
            {"categoryId": "math", "page": 1, "pageSize": 20},
        )

        conn = data["posts"]
        assert conn["total"] == 1
        item = conn["items"][0]
        assert item["id"] == post.id  # int
        assert item["title"] == "如何学习微积分"
        assert item["categoryId"] == "math"
        assert item["author"]["id"] == user_id  # int
        assert item["author"]["displayName"] == "爱丽丝"
        assert item["author"]["username"] == "alice"

    def should_filter_posts_by_category(self, client, db):
        user_id = _user(db)
        _post(db, author_id=user_id, title="数学", category_id="math")
        _post(db, author_id=user_id, title="物理", category_id="physics")

        data = self._run(
            client,
            "query($categoryId: ID){ posts(categoryId: $categoryId, page: 1, pageSize: 20){ total items{ id } } }",
            {"categoryId": "math"},
        )

        assert data["posts"]["total"] == 1

    def should_query_post_detail_with_bio_and_forward_count(self, client, db):
        user_id = _user(db, username="bob", nickname="鲍勃", email="bob@example.com")
        # 给 Profile 设置 bio
        prof = db.query(Profile).filter(Profile.user_id == user_id).first()
        prof.bio = "热爱物理与数学"
        db.flush()
        post = _post(db, author_id=user_id, title="物理之美", category_id="physics")
        post_orm = db.query(ForumPost).filter(ForumPost.id == post.id).first()
        post_orm.forward_count = 7
        db.flush()

        data = self._run(
            client,
            """
            query PostDetail($id: ID!) {
              post(id: $id) {
                id title content categoryId tags isPinned isFeatured
                bookmarkCount forwardCount createdAt
                author { id displayName avatar username bio }
              }
            }
            """,
            {"id": str(post.id)},
        )

        p = data["post"]
        assert p["id"] == post.id
        assert p["forwardCount"] == 7
        assert p["author"]["bio"] == "热爱物理与数学"
        assert p["author"]["displayName"] == "鲍勃"

    def should_return_null_when_post_missing(self, client, db):
        data = self._run(
            client,
            "query($id: ID!){ post(id: $id){ id } }",
            {"id": "999"},
        )
        assert data["post"] is None
