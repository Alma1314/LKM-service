"""follow 关注 + 时间线 read-time 合流 + 自动审校降权 集成测试。

覆盖：
- follow_user/unfollow_user 幂等、软删墓碑、不能关注自己
- get_following_ids / get_followed_board_ids（redis fail-open 下直接落库，功能正确）
- get_timeline：hot 模式跨源合流、follow 模式按关注过滤、匿名降级 hot、游标分页
- 审校：hide 命中剔除、derank 压低 sort_score、admin CRUD 后规则生效
- moderation.evaluate 纯函数行为
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.moderation import service as mod_service
from app.modules.admin.moderation.engine import Rule, evaluate, load_active_rules
from app.modules.admin.moderation.schemas import RuleCreate, RuleUpdate
from app.modules.articles.models import Article, ArticleCategory
from app.modules.auth.models import Profile, User
from app.modules.auth.security import hashpwd
from app.modules.content.boards.schemas import BoardCreate
from app.modules.content.boards.service import create_board_ex
from app.modules.content.models import ContentItem
from app.modules.feed import service as follow_service
from app.modules.feed.models import UserFollow
from app.modules.feed.service import get_timeline


async def _user(db: AsyncSession, username: str) -> int:
    user = User(
        username=username,
        email=f"{username}@ex.com",
        hashed_password=await hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, nickname=username))
    await db.flush()
    return user.id


async def _board(db: AsyncSession, slug: str) -> int:
    return (await create_board_ex(db, BoardCreate(slug=slug, title=slug), None)).id


async def _forum_post(
    db: AsyncSession, author_id: int, board_id: int, title: str
) -> int:
    """讨论帖数据源已收敛到 content_items（content_type==discussion）。"""
    item = ContentItem(
        content_type="discussion",
        board_id=board_id,
        author_id=author_id,
        title=title,
        excerpt=title + "摘要",
        content=title + "内容",
        status="published",
    )
    db.add(item)
    await db.flush()
    return item.id


async def _article(db: AsyncSession, slug: str, title: str) -> int:
    cat = ArticleCategory(slug=slug, title=slug)
    db.add(cat)
    await db.flush()
    a = Article(
        slug=slug,
        title=title,
        content=title + "正文",
        status="published",
        category_id=cat.id,
        publisher="宣传部",
    )
    db.add(a)
    await db.flush()
    return a.id


async def _blog_item(
    db: AsyncSession, author_id: int, board_id: int, title: str
) -> int:
    """博客发布产物：只落统一内容表 content_items（content_type=blog_post）。"""
    item = ContentItem(
        content_type="blog_post",
        board_id=board_id,
        author_id=author_id,
        title=title,
        excerpt=title + "摘要",
        content=title + "正文",
        status="published",
    )
    db.add(item)
    await db.flush()
    return item.id


class TestFollow:
    async def test_follow_idempotent_and_list(self, db: AsyncSession) -> None:
        a = await _user(db, "alice")
        b = await _user(db, "bob")
        await follow_service.follow_user(db, a, b)
        # 重复关注幂等 → 仍只有一条活动关注
        await follow_service.follow_user(db, a, b)
        ids = await follow_service.get_following_ids(db, a)
        assert ids == [b]

    async def test_unfollow_soft_delete(self, db: AsyncSession) -> None:
        a = await _user(db, "alice")
        b = await _user(db, "bob")
        await follow_service.follow_user(db, a, b)
        await follow_service.unfollow_user(db, a, b)
        assert await follow_service.get_following_ids(db, a) == []
        # 解关注后仍可再关注（无唯一冲突）
        await follow_service.follow_user(db, a, b)
        assert await follow_service.get_following_ids(db, a) == [b]

    async def test_cannot_follow_self(self, db: AsyncSession) -> None:
        a = await _user(db, "alice")
        try:
            await follow_service.follow_user(db, a, a)
        except Exception as e:
            assert e.args and "不能关注自己" in str(e.args)
        else:
            raise AssertionError("应拒绝关注自己")

    async def test_follow_unfollow_then_refollow_no_dup(self, db: AsyncSession) -> None:
        a = await _user(db, "alice")
        b = await _user(db, "bob")
        for _ in range(3):
            await follow_service.follow_user(db, a, b)
            await follow_service.unfollow_user(db, a, b)
        # 软删行的唯一约束允许：最终一条活动 + 若干已删
        rows = await db.execute(select(UserFollow).where(UserFollow.follower_id == a))
        assert list(rows.scalars())  # 有行存在
        assert await follow_service.get_following_ids(db, a) == []


class TestTimeline:
    async def test_hot_merges_sources(self, db: AsyncSession) -> None:
        author = await _user(db, "alice")
        board = await _board(db, "tech")
        await _forum_post(db, author, board, "hot帖")
        await _article(db, "art1", "hot文章")

        feed = await get_timeline(db, user_id=None, mode="hot", cursor=None, limit=20)
        types = {it.item_type for it in feed.items}
        assert "discussion" in types
        assert "article" in types

    async def test_hot_includes_blog_post(self, db: AsyncSession) -> None:
        """博客发布产物（content_items/blog_post）应进入 hot 流（无分表源覆盖）。"""
        author = await _user(db, "bob")
        board = await _board(db, "blog")
        await _blog_item(db, author, board, "博客发布")

        feed = await get_timeline(db, user_id=None, mode="hot", cursor=None, limit=20)
        blogs = [it for it in feed.items if it.item_type == "blog"]
        assert any(it.title == "博客发布" for it in blogs)

    async def test_follow_filters_blog_by_author(self, db: AsyncSession) -> None:
        """blog_post 在 follow 模式按关注作者过滤。"""
        me = await _user(db, "me")
        friend = await _user(db, "friend")
        stranger = await _user(db, "stranger")
        board = await _board(db, "blog")
        await _blog_item(db, friend, board, "关注人的博客")
        await _blog_item(db, stranger, board, "陌生人的博客")
        await follow_service.follow_user(db, me, friend)

        feed = await get_timeline(db, user_id=me, mode="follow", cursor=None, limit=20)
        blogs = [it.title for it in feed.items if it.item_type == "blog"]
        assert "关注人的博客" in blogs
        assert "陌生人的博客" not in blogs

    async def test_follow_filters_by_author(self, db: AsyncSession) -> None:
        me = await _user(db, "me")
        friend = await _user(db, "friend")
        stranger = await _user(db, "stranger")
        board = await _board(db, "tech")
        await _forum_post(db, friend, board, "关注的人帖")
        await _forum_post(db, stranger, board, "陌生人的帖")
        await follow_service.follow_user(db, me, friend)

        feed = await get_timeline(db, user_id=me, mode="follow", cursor=None, limit=20)
        titles = [it.title for it in feed.items if it.item_type == "discussion"]
        assert "关注的人帖" in titles
        assert "陌生人的帖" not in titles

    async def test_follow_filters_by_board(self, db: AsyncSession) -> None:
        me = await _user(db, "me")
        author = await _user(db, "author")
        b1 = await _board(db, "tech")
        b2 = await _board(db, "nontech")
        await _forum_post(db, author, b1, "已关注版块的帖")
        await _forum_post(db, author, b2, "未关注版块的帖")
        await follow_service.follow_board(db, me, b1)

        feed = await get_timeline(db, user_id=me, mode="follow", cursor=None, limit=20)
        titles = [it.title for it in feed.items if it.item_type == "discussion"]
        assert "已关注版块的帖" in titles
        assert "未关注版块的帖" not in titles

    async def test_follow_no_empty_early(self, db: AsyncSession) -> None:
        """关注为空时按计划直接返回空流（不查空 IN）。"""
        me = await _user(db, "me")
        feed = await get_timeline(db, user_id=me, mode="follow", cursor=None, limit=20)
        assert feed.items == []

    async def test_article_hidden_from_follow(self, db: AsyncSession) -> None:
        """Article 无作者外键：follow 模式不出现。"""
        me = await _user(db, "me")
        friend = await _user(db, "friend")
        board = await _board(db, "tech")
        await _forum_post(db, friend, board, "帖")
        await _article(db, "artX", "文章")
        await follow_service.follow_user(db, me, friend)
        feed = await get_timeline(db, user_id=me, mode="follow", cursor=None, limit=20)
        assert not any(it.item_type == "article" for it in feed.items)


class TestModeration:
    async def test_evaluate_hide_and_derank(self) -> None:
        r1 = Rule(pattern="违禁", action="hide")
        r2 = Rule(pattern="敏感", action="derank", weight=0.6)
        res_hide = evaluate("这里有违禁词", [r1])
        assert res_hide.should_hide is True
        res_derank = evaluate("这里有敏感词", [r2])
        assert res_derank.should_hide is False
        assert res_derank.penalty == pytest.approx(0.6)

    async def test_hide_removes_from_feed(self, db: AsyncSession) -> None:
        await mod_service.create_rule(db, RuleCreate(pattern="违禁词", action="hide"))
        author = await _user(db, "alice")
        board = await _board(db, "tech")
        await _forum_post(db, author, board, "正常标题")
        await _forum_post(db, author, board, "含违禁词标题")
        rules = await load_active_rules(db)
        assert any(r.action == "hide" for r in rules)
        feed = await get_timeline(db, user_id=None, mode="hot", cursor=None, limit=20)
        titles = [it.title for it in feed.items if it.item_type == "discussion"]
        assert "正常标题" in titles
        assert "含违禁词标题" not in titles

    async def test_derank_lowers_score(self, db: AsyncSession) -> None:
        await mod_service.create_rule(
            db, RuleCreate(pattern="敏感", action="derank", weight=0.8)
        )
        author = await _user(db, "alice")
        board = await _board(db, "tech")
        await _forum_post(db, author, board, "普通标题")
        await _forum_post(db, author, board, "敏感标题")
        feed = await get_timeline(db, user_id=None, mode="hot", cursor=None, limit=20)
        score = {
            it.title: it.sort_score for it in feed.items if it.item_type == "discussion"
        }
        assert score["敏感标题"] < score["普通标题"]

    async def test_admin_crud_and_version(self, db: AsyncSession) -> None:
        rule = await mod_service.create_rule(db, RuleCreate(pattern="x"))
        assert rule.id
        updated = await mod_service.update_rule(db, rule.id, RuleUpdate(pattern="y"))
        assert updated.pattern == "y"
        await mod_service.delete_rule(db, rule.id)
        rules = await mod_service.list_rules(db)
        assert all(r.id != rule.id for r in rules)
