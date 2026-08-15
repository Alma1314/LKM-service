"""官方文章示例数据。用法：uv run python -m app.modules.articles.seed"""

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.auth.models  # noqa: F401  注册剩余 ORM 映射类（同 alembic/env.py）
from app.db.models import Article, now_iso
from app.db.session import new_session

# Markdown 渲染测试文章（独立 md 文件作为单一内容源）
_MARKDOWN_TEST_CONTENT = (Path(__file__).parent / "markdown-test.md").read_text(
    encoding="utf-8"
)

SEED_ARTICLES: list[dict[str, object]] = [
    {
        "slug": "welcome-to-lkm",
        "title": "欢迎来到理科迷",
        "description": "理科迷官方社区正式上线，欢迎各位理科爱好者。",
        "cover": None,
        "category": "announcement",
        "content": "# 欢迎来到理科迷\n\n理科迷是一个理科爱好者的交流社区。\n\n- 分享知识\n- 参与竞赛\n- 探索科学",
        "publisher": "理科迷运营组",
        "department": "官方",
        "keywords": "公告,上线",
    },
    {
        "slug": "ai-in-science-education",
        "title": "AI 在理科教育中的应用",
        "description": "浅谈人工智能如何改变理科学习方式。",
        "cover": None,
        "category": "news",
        "content": "# AI 在理科教育中的应用\n\n人工智能正在重塑教育。\n\n## 自适应学习\n\nAI 可以根据学生水平推荐题目。",
        "publisher": "理科迷编辑部",
        "department": "内容",
        "keywords": "AI,教育",
    },
    {
        "slug": "why-the-sky-is-blue",
        "title": "为什么天空是蓝色的",
        "description": "用瑞利散射解释我们熟悉的自然现象。",
        "cover": None,
        "category": "science",
        "content": "# 为什么天空是蓝色的\n\n太阳光进入大气层后发生**瑞利散射**。\n\n```text\n散射强度 ∝ 1/波长^4\n```",
        "publisher": "理科迷编辑部",
        "department": "内容",
        "keywords": "科普,光学",
    },
    {
        "slug": "engineering-practices",
        "title": "工程实践：从零搭建一个服务",
        "description": "一次最小可用的后端服务搭建记录。",
        "cover": None,
        "category": "engineering",
        "content": "# 工程实践\n\n从零搭建一个服务，需要关注：\n\n1. 分层\n2. 测试\n3. 部署",
        "publisher": "理科迷工程组",
        "department": "工程",
        "keywords": "工程,后端",
    },
    {
        "slug": "markdown-test",
        "title": "Markdown 渲染测试",
        "description": "验证文章详情页 Markdown 渲染与侧栏目录（TOC）效果。",
        "cover": None,
        "category": "news",
        "content": _MARKDOWN_TEST_CONTENT,
        "publisher": "理科迷编辑部",
        "department": "测试",
        "keywords": "测试,Markdown",
    },
]


async def seed_articles(db: AsyncSession) -> int:
    count = 0
    for data in SEED_ARTICLES:
        slug = data["slug"]
        existing = (
            await db.execute(select(Article).where(Article.slug == slug))
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(Article(published=now_iso(), **data))
        count += 1
    await db.commit()
    return count


async def main() -> None:
    db = await new_session()
    try:
        count = await seed_articles(db)
        print(f"seeded {count} articles")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
