"""articles 迁移 RBAC：官方文章写/审/删/分类需对应权限点。

迁移目标：写端点由 service 内 assert_super_admin 改为路由层 RequirePermission(articles_*)。
- create/patch/soft_delete → articles_publish
- hard_delete/review → articles_review
- 分类 CRUD → articles_category_manage
- 删评论 → check_owner(ArticleComment.user_id) + article_owner_comment_delete
"""

from app.db.models import (
    Article,
    ArticleComment,
    Profile,
    RolePermission,
    User,
)
from app.modules.articles.schemas import CategoryCreate
from app.modules.articles.service import create_category_ex
from app.modules.auth.security import create_access_token
from tests.conftest import DB, Client


def _h(u: User, role: str = "member") -> dict[str, str]:
    # create_access_token 的 role 是必填（security.py:61）；CurrentUser.role 来自 DB profile.role。
    tok = create_access_token(user_id=u.id, account_level=u.account_level, role=role)
    return {"Authorization": f"Bearer {tok}"}


async def _user(db: DB, username: str, level: str, role: str) -> User:
    u = User(
        username=username,
        hashed_password="rbac-test-placeholder-not-a-real-hash",
        account_level=level,
    )
    db.add(u)
    await db.flush()
    db.add(Profile(user_id=u.id, role=role, nickname=username[:10]))
    await db.flush()
    return u


async def _grant(db: DB, role_name: str, permission: str) -> None:
    db.add(RolePermission(role_name=role_name, permission=permission))
    await db.flush()


async def _category(db: DB) -> int:
    cat = await create_category_ex(db, CategoryCreate(slug="news", title="news"))
    return int(cat.id)


async def test_member_cannot_publish_article(db: DB, client: Client) -> None:
    # normal/member 无 articles.publish → 403（权限点在路由层拦截，早于 service 建文）
    cid = await _category(db)
    u = await _user(db, "member_pub", "normal", "member")
    r = await client.post(
        "/api/v1/articles",
        headers=_h(u),
        json={"slug": "x", "title": "t", "content": "c", "category_id": cid},
    )
    assert r.status_code == 403


async def test_org_member_cannot_review_article(db: DB, client: Client) -> None:
    # admin:org_member 有后台能力但无 articles.review → 审核 403（区分 super_admin 与 org_member）
    u = await _user(db, "org_admin", "admin", "org_member")
    r = await client.post(
        "/api/v1/articles/official-1/review",
        headers=_h(u, role="org_member"),
        json={"approve": True},
    )
    assert r.status_code == 403


async def test_super_admin_can_publish_article(db: DB, client: Client) -> None:
    # super_admin 默认授予 articles.publish；显式补授权以便测试库判权限（create_all 不自动 seed）
    await _grant(db, "admin:super_admin", "articles.publish")
    cid = await _category(db)
    u = await _user(db, "sup", "admin", "super_admin")
    r = await client.post(
        "/api/v1/articles",
        headers=_h(u, role="super_admin"),
        json={
            "slug": "official-1",
            "title": "t",
            "content": "c",
            "category_id": cid,
        },
    )
    assert r.status_code == 200
    assert (r.json().get("data") or {}).get("slug") == "official-1"


async def _article(db: DB, category_id: int | None = None) -> int:
    """直插一条 Article，供评论挂在 article_id 下。返回文章 id。"""
    cid = category_id if category_id is not None else await _category(db)
    art = Article(slug="rbac-cmt", title="t", category_id=cid, content="c")
    db.add(art)
    await db.flush()
    return int(art.id)


async def _comment(db: DB, article_id: int, author_id: int) -> int:
    """直插一条评论（评论作者 = author_id），返回评论 id。"""
    cmt = ArticleComment(article_id=article_id, user_id=author_id, content="c")
    db.add(cmt)
    await db.flush()
    return int(cmt.id)


async def test_comment_author_can_delete_own(db: DB, client: Client) -> None:
    # 用例1：评论作者（user_id==cur.id）可删自己评论 → 200（走 check_owner 属主判定，无需权限点）
    aid = await _article(db)
    author = await _user(db, "cmt_author", "normal", "member")
    cmt_id = await _comment(db, aid, author.id)
    r = await client.delete(f"/api/v1/articles/comments/{cmt_id}", headers=_h(author))
    assert r.status_code == 200


async def test_other_member_cannot_delete_comment(db: DB, client: Client) -> None:
    # 用例2：他人（非评论作者、非 super_admin）删评论 → 403
    aid = await _article(db)
    author = await _user(db, "cmt_author2", "normal", "member")
    cmt_id = await _comment(db, aid, author.id)
    other = await _user(db, "cmt_other", "normal", "member")
    r = await client.delete(f"/api/v1/articles/comments/{cmt_id}", headers=_h(other))
    assert r.status_code == 403


async def test_super_admin_can_delete_any_comment(db: DB, client: Client) -> None:
    # 用例3：super_admin 授 article.owner_comment_delete 可代删任意评论（非作者的迁移扩展）→ 200
    await _grant(db, "admin:super_admin", "article.owner_comment_delete")
    aid = await _article(db)
    author = await _user(db, "cmt_author3", "normal", "member")
    cmt_id = await _comment(db, aid, author.id)
    sup = await _user(db, "sup_del", "admin", "super_admin")
    r = await client.delete(
        f"/api/v1/articles/comments/{cmt_id}", headers=_h(sup, role="super_admin")
    )
    assert r.status_code == 200
