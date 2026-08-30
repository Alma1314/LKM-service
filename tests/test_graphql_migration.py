from typing import Any

from httpx import AsyncClient

from app.db.models import Board, ContentItem, ContentStatus, ContentType


async def _run(client: AsyncClient, query: str, variables: dict[str, Any]) -> Any:
    resp = await client.post("/graphql", json={"query": query, "variables": variables})
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert "errors" not in body, body.get("errors")
    return body["data"]


class TestContentGraphQL:
    """content 只读 GraphQL 契约测试（对齐前端 content.graphql.ts）。"""

    async def should_query_content_items(self, client: AsyncClient, db):
        # 需要后端 board + user 造数。此处用最小断言：查询空库返回空列表且无 errors。
        data = await _run(
            client,
            """
            query {
              contentItems(page: 1, pageSize: 10) {
                items { id title authorName contentType boardId }
                total page pages
              }
            }
            """,
            {},
        )
        assert data["contentItems"]["total"] >= 0
        assert isinstance(data["contentItems"]["items"], list)

    async def should_hide_unpublished_detail(self, client: AsyncClient, db):
        """contentItem 详情仅暴露 PUBLISHED；草稿/待审等未发布内容返回 null。"""
        b = Board(title="b", slug="b", description="", status="active")
        db.add(b)
        await db.flush()
        draft = ContentItem(
            content_type=ContentType.ARTICLE,
            board_id=b.id,
            title="草稿",
            content="未发布正文",
            status=ContentStatus.DRAFT,
        )
        published = ContentItem(
            content_type=ContentType.ARTICLE,
            board_id=b.id,
            title="已发布",
            content="公开正文",
            status=ContentStatus.PUBLISHED,
        )
        db.add_all([draft, published])
        await db.flush()

        data = await _run(
            client,
            "query($id: Int!) { contentItem(id: $id) { id title content } }",
            {"id": draft.id},
        )
        assert data["contentItem"] is None

        data = await _run(
            client,
            "query($id: Int!) { contentItem(id: $id) { id title content } }",
            {"id": published.id},
        )
        assert data["contentItem"] is not None
        assert data["contentItem"]["title"] == "已发布"


class TestArticlesGraphQL:
    """articles（官网文章）只读 GraphQL 契约测试。"""

    async def should_query_articles(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query {
              articles(page: 1, pageSize: 20) {
                items { slug title categoryTitle categoryId views }
                total page pages
              }
            }
            """,
            {},
        )
        assert isinstance(data["articles"]["items"], list)
        assert isinstance(data["articles"]["total"], int)

    async def should_search_articles(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query($q: String!) {
              searchArticles(q: $q, page: 1, pageSize: 20) {
                items { slug title }
                total
              }
            }
            """,
            {"q": "微积分"},
        )
        assert "searchArticles" in data

    async def should_query_article_tags(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query {
              articleTags { name articleCount }
            }
            """,
            {},
        )
        assert isinstance(data["articleTags"], list)
        for t in data["articleTags"]:
            assert "name" in t and "articleCount" in t

    async def should_query_about(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query {
              about { title description maintainer }
            }
            """,
            {},
        )
        assert data["about"]["title"]
        assert "description" in data["about"]
        assert "maintainer" in data["about"]


class TestColumnsGraphQL:
    """columns(专栏) 只读 GraphQL 契约测试（对齐前端 column.graphql.ts）。"""

    async def should_query_columns(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query {
              columns(page: 1) {
                items { id title slug authorName boardId }
                total page pages
              }
            }
            """,
            {},
        )
        assert isinstance(data["columns"]["items"], list)

    async def should_query_column_posts(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query($id: Int!) {
              columnPosts(columnId: $id, page: 1) {
                items { id title summary viewCount }
                total
              }
            }
            """,
            {"id": 1},
        )
        assert "columnPosts" in data


class TestBlogGraphQL:
    """blog(博客 Series/Git 文件) 只读 GraphQL 契约测试。"""

    async def should_query_series(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query {
              blogSeries {
                items { id title ownerId starCount isStarred }
                total page pages
              }
            }
            """,
            {},
        )
        assert isinstance(data["blogSeries"]["items"], list)

    async def should_query_series_detail(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query($id: Int!) {
              blogSeriesDetail(seriesId: $id) {
                id title
                fileTree { name type children { name type } }
              }
            }
            """,
            {"id": 1},
        )
        # 不存在的 series 应返回 null（resolver 捕获异常）
        assert data["blogSeriesDetail"] is None

    async def should_query_blog_file_content_not_found(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query($id: Int!, $filepath: String!) {
              blogFileContent(seriesId: $id, filepath: $filepath) {
                filepath content
              }
            }
            """,
            {"id": 999999, "filepath": "README.md"},
        )
        # 不存在的 series 应返回 null（resolver 捕获 SERIES_NOT_FOUND）
        assert data["blogFileContent"] is None


class TestProjectsGraphQL:
    """projects(项目) 只读 GraphQL 契约测试（复用 projects.service）。"""

    async def should_query_projects(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query {
              projects {
                items { id title summary members { id displayName roleInProject } }
              }
            }
            """,
            {},
        )
        assert isinstance(data["projects"]["items"], list)

    async def should_query_project(self, client: AsyncClient, db):
        data = await _run(
            client,
            """
            query($id: Int!) {
              project(projectId: $id) { id title summary }
            }
            """,
            {"id": 1},
        )
        # 不存在的 project 应返回 null（resolver 捕获 NOT_FOUND）
        assert data["project"] is None
