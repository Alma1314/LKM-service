"""Tests for Github OAuth — service_oauth auth URL generation and callback logic."""
import pytest

import app.modules.auth.models  # pyright: ignore[reportUnusedImport]
from app.core.config import settings
from app.modules.auth.models import OAuthState


class TestGithubAuthUrl:
    def should_contain_github_authorize_url(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        assert "github.com/login/oauth/authorize" in url

    def should_contain_client_id(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        assert f"client_id={settings.github_client_id}" in url

    def should_contain_user_email_scope(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        assert "scope=user" in url
        assert "email" in url

    def should_contain_redirect_uri(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        assert "redirect_uri=" in url

    def should_generate_server_state_token(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        # state is now server-generated; must be non-empty
        assert "&state=" in url
        # state should not be the empty placeholder
        state_idx = url.index("&state=") + len("&state=")
        state_value = url[state_idx:]
        if "&" in state_value:
            state_value = state_value.split("&")[0]
        assert len(state_value) > 0


class TestOAuthState:
    def should_store_and_consume_state(self, db):
        from app.modules.auth.service_oauth import _generate_oauth_state, _consume_oauth_state

        state = _generate_oauth_state(db, "login")
        assert len(state) > 0

        records = db.query(OAuthState).filter(OAuthState.state == state).all()
        assert len(records) == 1
        assert not records[0].consumed

        _consume_oauth_state(db, state, "login")
        db.refresh(records[0])
        assert records[0].consumed

    def should_reject_already_consumed_state(self, db):
        from app.modules.auth.service_oauth import _generate_oauth_state, _consume_oauth_state
        from app.core.err import BizError

        state = _generate_oauth_state(db, "login")
        _consume_oauth_state(db, state, "login")

        with pytest.raises(BizError):
            _consume_oauth_state(db, state, "login")

    def should_reject_wrong_purpose(self, db):
        from app.modules.auth.service_oauth import _generate_oauth_state, _consume_oauth_state
        from app.core.err import BizError

        state = _generate_oauth_state(db, "login")
        with pytest.raises(BizError):
            _consume_oauth_state(db, state, "bind")


class TestOauthRouterRedirect:
    """Github callback 重定向到前端（302）—— 携带令牌 / temp_token / 绑定结果。"""

    def should_redirect_login_callback_with_tokens(self, db):
        import asyncio
        from unittest.mock import AsyncMock, patch
        from fastapi.responses import RedirectResponse

        from app.modules.auth import router_oauth
        from urllib.parse import parse_qs, urlparse

        payload = {
            "access_token": "acc123",
            "refresh_token": "ref123",
            "temp_token": None,
            "requires_2fa": False,
            "setup_required": False,
            "user_id": 1,
            "account_level": "normal",
        }

        with patch.object(
            router_oauth.service_oauth,
            "handle_github_callback",
            new=AsyncMock(return_value=payload),
        ):
            resp = asyncio.run(router_oauth.github_callback(code="c", state="s", db=db))

        assert isinstance(resp, RedirectResponse)
        assert resp.status_code in (302, 307)
        # 令牌通过 URL fragment 回传，不进 query，避免泄露
        qs = parse_qs(urlparse(resp.headers["location"]).fragment)
        assert qs["access_token"] == ["acc123"]
        assert qs["refresh_token"] == ["ref123"]
        assert "temp_token" not in qs

    def should_redirect_login_callback_with_temp_token_when_2fa(self, db):
        import asyncio
        from unittest.mock import AsyncMock, patch
        from fastapi.responses import RedirectResponse
        from urllib.parse import parse_qs, urlparse

        from app.modules.auth import router_oauth

        payload = {
            "access_token": None,
            "refresh_token": None,
            "temp_token": "tmp999",
            "requires_2fa": True,
            "setup_required": False,
            "user_id": 1,
            "account_level": "admin",
        }

        with patch.object(
            router_oauth.service_oauth,
            "handle_github_callback",
            new=AsyncMock(return_value=payload),
        ):
            resp = asyncio.run(router_oauth.github_callback(code="c", state="s", db=db))

        qs = parse_qs(urlparse(resp.headers["location"]).fragment)
        assert qs["temp_token"] == ["tmp999"]
        assert qs["requires_2fa"] == ["true"]
        assert "access_token" not in qs

    def should_redirect_bind_callback_on_success(self, db):
        import asyncio
        from unittest.mock import AsyncMock, patch
        from fastapi.responses import RedirectResponse
        from urllib.parse import parse_qs, urlparse

        from app.modules.auth import router_oauth

        with patch.object(
            router_oauth.service_oauth,
            "bind_github",
            new=AsyncMock(return_value={"message": "Github account bound"}),
        ):
            resp = asyncio.run(router_oauth.github_bind_callback(code="c", state="s", db=db))

        assert isinstance(resp, RedirectResponse)
        # 绑定回调结果经 URL fragment 回传
        qs = parse_qs(urlparse(resp.headers["location"]).fragment)
        assert qs["success"] == ["1"]

    def should_redirect_bind_callback_on_biz_error(self, db):
        import asyncio
        from unittest.mock import AsyncMock, patch
        from fastapi.responses import RedirectResponse
        from urllib.parse import parse_qs, urlparse

        from app.core.err import BizError
        from app.modules.auth import router_oauth
        from app.modules.auth.errors import AuthErr

        async def _boom(db, code, state):
            raise BizError(AuthErr.OAUTH_EMAIL_TAKEN)

        with patch.object(router_oauth.service_oauth, "bind_github", new=_boom):
            resp = asyncio.run(router_oauth.github_bind_callback(code="c", state="s", db=db))

        assert isinstance(resp, RedirectResponse)
        qs = parse_qs(urlparse(resp.headers["location"]).fragment)
        assert qs["success"] == ["0"]
        assert qs["error"] == ["OAUTH_EMAIL_TAKEN"]
