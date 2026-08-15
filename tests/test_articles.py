import datetime

from app.db.models import Article


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
        category=category,
        content="# 标题\n\n正文内容",
        publisher="运营组",
        department="官方",
        keywords="公告,上线",
        published=datetime.datetime.now(datetime.UTC),
    )
    db.add(article)
    await db.commit()
    return article


async def test_list_articles_pagination(db, client):
    await _make_article(db, "a-1", "news")
    await _make_article(db, "a-2", "news")
    await _make_article(db, "a-3", "science")

    resp = await client.get("/api/v1/articles", params={"page": 1, "page_size": 2})

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["total"] == 3
    assert len(body["data"]["items"]) == 2


async def test_get_article_detail(db, client):
    await _make_article(db, "a-1", "news")

    resp = await client.get("/api/v1/articles/a-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["slug"] == "a-1"
    assert data["content"] == "# 标题\n\n正文内容"
    assert data["keywords"] == ["公告", "上线"]


async def test_get_article_not_found(db, client):
    resp = await client.get("/api/v1/articles/does-not-exist")
    assert resp.status_code == 404


async def test_list_categories(db, client):
    await _make_article(db, "a-1", "news")
    await _make_article(db, "a-2", "science")

    resp = await client.get("/api/v1/articles/categories")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    items = body["data"]["items"]
    slugs = {c["slug"]: c for c in items}
    assert slugs["news"]["name"] == "科技新闻"
    assert slugs["news"]["article_count"] == 1
    assert slugs["science"]["article_count"] == 1


async def test_categories_route_not_swallowed_by_slug(db, client):
    resp = await client.get("/api/v1/articles/categories")
    # 若被 /{slug} 吞掉，会返回 404（slug=categories 不存在）；正确应是分类列表
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
