import datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Article, ArticleCategory, Profile, User
from app.modules.auth.security import create_access_token, hashpwd


async def _run_graphql(
    client: AsyncClient, query: str, variables: dict[str, Any]
) -> Any:
    """只读端点已下线，改由 GraphQL 承担读取。走 /graphql 返回 data。"""
    resp = await client.post("/graphql", json={"query": query, "variables": variables})
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert "errors" not in body, body.get("errors")
    return body["data"]


# 分类 slug -> title 映射。news 沿用"科技新闻"以匹配 test_list_categories 断言；
# 其余 slug 用其自身作为 title（仅测试定位用）。
_CATEGORY_TITLES: dict[str, str] = {"news": "科技新闻"}


async def _resolve_or_create_category(db, slug: str) -> int:
    """按 slug 取分类；不存在则新建，返回分类 id（幂等）。"""
    existing_id = await db.scalar(
        select(ArticleCategory.id).where(ArticleCategory.slug == slug)
    )
    if existing_id is not None:
        return int(existing_id)
    cat = ArticleCategory(slug=slug, title=_CATEGORY_TITLES.get(slug, slug), sort=0)
    db.add(cat)
    await db.flush()
    return int(cat.id)


async def _make_article(
    db,
    slug: str = "a-1",
    category: str = "news",
    title: str = "示例文章",
) -> Article:
    article = Article(
        slug=slug,
        title=title,
        description="摘要",
        cover=None,
        category_id=await _resolve_or_create_category(db, category),
        content="# 标题\n\n正文内容",
        publisher="运营组",
        department="官方",
        keywords="公告,上线",
        published=datetime.datetime.now(datetime.UTC),
    )
    db.add(article)
    await db.commit()
    return article


async def _make_user(
    db,
    username: str = "cu",
    email: str = "cu@x.com",
) -> int:
    user = User(
        username=username,
        email=email,
        hashed_password=await hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id))
    await db.flush()
    return user.id


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login_token(
    db,
    username: str = "cu",
    email: str = "cu@x.com",
) -> tuple[int, str]:
    uid = await _make_user(db, username, email)
    token = create_access_token(user_id=uid, account_level="normal", role="member")
    return uid, token


async def test_list_articles_pagination(db, client):
    await _make_article(db, "a-1", "news")
    await _make_article(db, "a-2", "news")
    await _make_article(db, "a-3", "science")

    data = await _run_graphql(
        client,
        """
        query($page: Int!) {
          articles(page: $page, pageSize: 2) { items { slug } total page pages }
        }
        """,
        {"page": 1},
    )
    page_data = data["articles"]
    assert page_data["total"] == 3
    assert len(page_data["items"]) == 2


async def test_get_article_detail(db, client):
    await _make_article(db, "a-1", "news")

    data = await _run_graphql(
        client,
        """
        query($slug: String!) {
          article(slug: $slug) {
            slug content keywords readingTime
          }
        }
        """,
        {"slug": "a-1"},
    )
    detail = data["article"]
    assert detail["slug"] == "a-1"
    assert detail["content"] == "# 标题\n\n正文内容"
    assert detail["keywords"] == ["公告", "上线"]
    assert detail["readingTime"] >= 1


async def test_get_article_not_found(db, client):
    # 不存在的 slug：GraphQL resolver 返回 null
    resp = await client.post(
        "/graphql",
        json={
            "query": "query($slug: String!) { article(slug: $slug) { slug } }",
            "variables": {"slug": "does-not-exist"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["article"] is None


async def test_list_categories(db, client):
    await _make_article(db, "a-1", "news")
    await _make_article(db, "a-2", "science")

    data = await _run_graphql(
        client,
        """
        query { articleCategories { slug name articleCount } }
        """,
        {},
    )
    items = data["articleCategories"]
    slugs = {c["slug"]: c for c in items}
    assert slugs["news"]["name"] == "科技新闻"
    assert slugs["news"]["articleCount"] == 1
    assert slugs["science"]["articleCount"] == 1


async def test_search_articles_sqlite(db, client):
    await _make_article(db, "a-1", "news", title="机器学习入门")
    data = await _run_graphql(
        client,
        """
        query($q: String!) {
          searchArticles(q: $q, page: 1) { items { slug } total }
        }
        """,
        {"q": "机器"},
    )
    assert data["searchArticles"]["total"] >= 1


async def test_search_requires_q(db, client):
    # q 为必填参数：缺失时 GraphQL 返回校验/执行错误
    resp = await client.post(
        "/graphql",
        json={"query": "query { searchArticles { items { slug } } }", "variables": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "errors" in body


async def test_like_toggle(db, client):
    await _make_article(db, "a-1", "news")
    _, token = await _login_token(db)
    h = _auth(token)
    r1 = await client.post("/api/v1/articles/a-1/like", headers=h)
    assert r1.status_code == 200
    d1 = r1.json()["data"]
    assert d1["liked"] is True and d1["like_count"] == 1
    r2 = await client.post("/api/v1/articles/a-1/like", headers=h)
    d2 = r2.json()["data"]
    assert d2["liked"] is False and d2["like_count"] == 0


async def test_like_requires_auth(db, client):
    await _make_article(db, "a-1", "news")
    resp = await client.post("/api/v1/articles/a-1/like")
    assert resp.status_code == 403


async def test_comment_create_and_count(db, client):
    await _make_article(db, "a-1", "news")
    _, token = await _login_token(db)
    r = await client.post(
        "/api/v1/articles/a-1/comments",
        headers=_auth(token),
        json={"content": "好文！"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["content"] == "好文！"
    detail = await _run_graphql(
        client,
        "query($slug: String!) { article(slug: $slug) { comments } }",
        {"slug": "a-1"},
    )
    assert detail["article"]["comments"] == 1


async def test_comment_reply(db, client):
    await _make_article(db, "a-1", "news")
    _, token = await _login_token(db)
    h = _auth(token)
    parent = (
        await client.post(
            "/api/v1/articles/a-1/comments",
            headers=h,
            json={"content": "父评论"},
        )
    ).json()["data"]
    child = await client.post(
        "/api/v1/articles/a-1/comments",
        headers=h,
        json={"content": "子回复", "parent_id": parent["id"]},
    )
    assert child.status_code == 200
    assert child.json()["data"]["parent_id"] == parent["id"]
    # 评论总数改为经 GraphQL article.comments 读回
    detail = await _run_graphql(
        client,
        "query($slug: String!) { article(slug: $slug) { comments } }",
        {"slug": "a-1"},
    )
    assert detail["article"]["comments"] == 2


async def test_comment_requires_auth(db, client):
    await _make_article(db, "a-1", "news")
    resp = await client.post("/api/v1/articles/a-1/comments", json={"content": "x"})
    assert resp.status_code == 403


async def test_delete_comment_owner_only(db, client):
    await _make_article(db, "a-1", "news")
    _, token = await _login_token(db, username="owner")
    cmt_id = (
        await client.post(
            "/api/v1/articles/a-1/comments",
            headers=_auth(token),
            json={"content": "x"},
        )
    ).json()["data"]["id"]
    other_id = await _make_user(db, username="other", email="other@x.com")
    other_token = create_access_token(
        user_id=other_id, account_level="normal", role="member"
    )
    forbid = await client.delete(
        f"/api/v1/articles/comments/{cmt_id}", headers=_auth(other_token)
    )
    assert forbid.status_code == 403
    ok = await client.delete(
        f"/api/v1/articles/comments/{cmt_id}", headers=_auth(token)
    )
    assert ok.status_code == 200
    detail = await _run_graphql(
        client,
        "query($slug: String!) { article(slug: $slug) { comments } }",
        {"slug": "a-1"},
    )
    assert detail["article"]["comments"] == 0
