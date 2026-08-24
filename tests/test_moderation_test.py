"""自动审校规则测试端点验证。

覆盖：
- mod_service.test_rules：命中/未命中、derank 累加 penalty、hide 触发 should_hide
- HTTP POST /admin/moderation/rules/test（require_admin_2fa）：无 2FA 信任报 MFA_REQUIRED，
  带 2FA 信任管理 cookie 后返回命中明细。
"""

import pytest
from httpx import AsyncClient

from app.db.models import Profile, User
from app.modules.admin.deps import COOKIE_NAME, COOKIE_PATH, create_admin_access_token
from app.modules.moderation import service as mod_service
from app.modules.moderation.schemas import RuleCreate
from tests.conftest import DB


async def _admin(db: DB, username: str) -> User:
    u = User(
        username=username,
        email=f"{username}@ex.com",
        hashed_password="mod-test-placeholder-not-a-real-hash",
        account_level="admin",
    )
    db.add(u)
    await db.flush()
    db.add(Profile(user_id=u.id, role="super_admin", nickname=username))
    await db.flush()
    return u


class TestTestRulesService:
    async def test_hits_derank(self, db: DB) -> None:
        await mod_service.create_rule(db, RuleCreate(pattern="敏感词", weight=0.8))
        result = await mod_service.test_rules(db, "内容里有敏感词")
        assert result.matched is True
        assert result.penalty == pytest.approx(0.8)
        assert result.should_hide is False
        assert [h.pattern for h in result.hits] == ["敏感词"]

    async def test_misses(self, db: DB) -> None:
        await mod_service.create_rule(db, RuleCreate(pattern="白名单词"))
        result = await mod_service.test_rules(db, "完全无关的内容")
        assert result.matched is False
        assert result.penalty == 0.0
        assert result.should_hide is False
        assert result.hits == []

    async def test_hide_sets_should_hide(self, db: DB) -> None:
        await mod_service.create_rule(db, RuleCreate(pattern="违禁", action="hide"))
        result = await mod_service.test_rules(db, "包含违禁内容")
        assert result.should_hide is True

    async def test_accumulates_penalty(self, db: DB) -> None:
        await mod_service.create_rule(db, RuleCreate(pattern="甲", weight=0.4))
        await mod_service.create_rule(db, RuleCreate(pattern="乙", weight=0.3))
        result = await mod_service.test_rules(db, "甲和乙都有")
        assert result.matched is True
        assert result.penalty == pytest.approx(0.7)
        assert len(result.hits) == 2


class TestTestRulesHttp:
    async def test_requires_2fa_trusted_admin(
        self, db: DB, client: AsyncClient
    ) -> None:
        admin = await _admin(db, "root")
        tok = create_admin_access_token(admin, mfa_verified=False)
        client.cookies.set(COOKIE_NAME, tok, path=COOKIE_PATH)
        resp = await client.post(
            "/api/v1/admin/moderation/rules/test", json={"text": "hello"}
        )
        # 无 1h 2FA 信任 → MFA_REQUIRED（code=4，HTTP 401）
        assert resp.status_code == 401
        assert resp.json()["code"] == 4

    async def test_returns_hit_detail(self, db: DB, client: AsyncClient) -> None:
        await mod_service.create_rule(db, RuleCreate(pattern="敏感", weight=0.5))
        admin = await _admin(db, "root")
        tok = create_admin_access_token(admin, mfa_verified=True)
        client.cookies.set(COOKIE_NAME, tok, path=COOKIE_PATH)
        resp = await client.post(
            "/api/v1/admin/moderation/rules/test", json={"text": "本段含敏感字"}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["matched"] is True
        assert data["total_rules"] == 1
        assert data["penalty"] == pytest.approx(0.5)
        assert data["hits"][0]["pattern"] == "敏感"
