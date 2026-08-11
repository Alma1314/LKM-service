"""Github OAuth 服务 —— 授权 URL、处理回调、绑定账户。"""

import secrets
from typing import Any, cast

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.err import BizError
from app.modules.auth.errors import AuthErr
from app.db.models import Profile, User, expires_at, now_iso
from app.db.repo import consume_once, get_or_raise
from app.modules.auth.models import OAuthState, UserOAuth
from app.modules.auth.service_auth import finalize_auth_response, log_audit, upgrade_to_normal


async def _generate_oauth_state(db: AsyncSession, purpose: str, user_id: int | None = None) -> str:
    """生成一个高熵的 OAuth state 令牌，存储并返回它。bind 场景关联发起用户。"""
    state = secrets.token_urlsafe(32)
    expiry = expires_at(minutes=10)
    db.add(OAuthState(state=state, purpose=purpose, user_id=user_id, expires_at=expiry))
    await db.flush()
    return state


async def _consume_oauth_state(db: AsyncSession, state: str, purpose: str) -> OAuthState:
    """消耗一次 OAuth state，返回该记录（含 user_id，供绑定归属）。无效则抛错。"""
    consumed = await consume_once(
        db,
        OAuthState,
        {"consumed": True},
        OAuthState.state == state,
        OAuthState.consumed.is_(False),
        OAuthState.purpose == purpose,
        OAuthState.expires_at > now_iso(),
    )
    if not consumed:
        raise BizError(AuthErr.OAUTH_PROVIDER_ERROR, "Invalid or expired OAuth state")
    row = (await db.execute(select(OAuthState).where(OAuthState.state == state))).scalars().first()
    if not row:
        raise BizError(AuthErr.OAUTH_PROVIDER_ERROR, "Invalid or expired OAuth state")
    return row


async def get_github_auth_url(db: AsyncSession, purpose: str = "login", user_id: int | None = None) -> str:
    state = await _generate_oauth_state(db, purpose, user_id)
    return (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        f"&redirect_uri={settings.github_redirect_uri}"
        f"&scope=user:email"
        f"&state={state}"
    )


async def _exchange_github_token(code: str) -> str:
    """将 OAuth 授权码兑换为 GitHub 访问令牌。"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        data = resp.json()
        access_token = data.get("access_token")
        if not access_token:
            raise BizError(AuthErr.OAUTH_PROVIDER_ERROR, data.get("error_description", "No access token"))
        return access_token


async def _get_github_user(access_token: str) -> dict[str, Any]:
    """获取 GitHub 用户资料和主邮箱。"""
    headers = {"Authorization": f"token {access_token}"}
    async with httpx.AsyncClient() as client:
        # 获取用户资料
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        user_data = cast(dict[str, Any], user_resp.json())
        if "id" not in user_data:
            raise BizError(AuthErr.OAUTH_PROVIDER_ERROR, "Failed to fetch GitHub user")

        # 获取邮箱列表
        emails_resp = await client.get("https://api.github.com/user/emails", headers=headers)
        emails_data = emails_resp.json()
        primary_email: str | None = None
        if isinstance(emails_data, list):
            entries = cast(list[Any], emails_data)
            for entry in entries:
                if entry.get("primary") and entry.get("verified"):
                    primary_email = entry["email"]
                    break
            # 备选方案：第一个已验证的邮箱
            if primary_email is None:
                for entry in entries:
                    if entry.get("verified"):
                        primary_email = entry["email"]
                        break

        return {
            "provider_user_id": str(user_data["id"]),
            "provider_email": primary_email,
            "login": user_data.get("login", ""),
        }


async def handle_github_callback(db: AsyncSession, code: str, state: str) -> dict[str, Any]:
    await _consume_oauth_state(db, state, "login")  # login 场景无需用户归属
    access_token = await _exchange_github_token(code)
    gh_user = await _get_github_user(access_token)

    # 1. 现有 OAuth 绑定
    oauth = (
        await db.execute(
            select(UserOAuth).where(
                UserOAuth.provider == "github",
                UserOAuth.provider_user_id == gh_user["provider_user_id"],
            )
        )
    ).scalars().first()
    if oauth:
        user = await get_or_raise(
            db, User, AuthErr.USER_NOT_FOUND, User.id == int(oauth.user_id),  # type: ignore[arg-type]
            options=(selectinload(User.profile),),
        )
        return await _oauth_login_response(db, user)  # type: ignore[arg-type]

    # 2. 通过邮箱查找现有用户 -> 绑定
    if gh_user["provider_email"]:
        user = (await db.execute(select(User).where(User.email == gh_user["provider_email"]))).scalars().first()
        if user:
            db.add(
                UserOAuth(
                    user_id=int(user.id),  # type: ignore[arg-type]
                    provider="github",
                    provider_user_id=gh_user["provider_user_id"],
                    provider_email=gh_user["provider_email"],
                )
            )
            await db.flush()
            await upgrade_to_normal(db, user)  # type: ignore[arg-type]
            return await _oauth_login_response(db, user)  # type: ignore[arg-type]

    # 3. 创建新用户
    username = gh_user["login"]
    # 确保唯一性
    suffix = 1
    base = username
    while (await db.execute(select(User).where(User.username == username))).scalars().first():
        username = f"{base}{suffix}"
        suffix += 1

    user = User(
        username=username,
        email=gh_user["provider_email"],
        hashed_password="",
        account_level="normal",
    )
    db.add(user)
    await db.flush()

    db.add(Profile(user_id=int(user.id), role="member"))
    await db.flush()

    db.add(
        UserOAuth(
            user_id=int(user.id),
            provider="github",
            provider_user_id=gh_user["provider_user_id"],
            provider_email=gh_user["provider_email"],
        )
    )
    await db.flush()

    await log_audit(db, user.id, "oauth_login", "github")

    return await _oauth_login_response(db, user)


async def _oauth_login_response(db: AsyncSession, user: User) -> dict[str, Any]:
    """检查 TOTP 要求并返回认证响应。"""
    return await finalize_auth_response(db, user)


async def bind_github(db: AsyncSession, code: str, state: str) -> dict[str, Any]:
    """绑定 GitHub 到发起绑定的用户（user_id 由 OAuth state 记录携带，回调无需 JWT）。"""
    st = await _consume_oauth_state(db, state, "bind")
    user_id = st.user_id
    if not user_id:
        raise BizError(AuthErr.OAUTH_PROVIDER_ERROR, "Bind session lost its owner")
    access_token = await _exchange_github_token(code)
    gh_user = await _get_github_user(access_token)

    existing_oauth = (
        await db.execute(
            select(UserOAuth).where(
                UserOAuth.provider == "github",
                UserOAuth.provider_user_id == gh_user["provider_user_id"],
            )
        )
    ).scalars().first()
    if existing_oauth:
        raise BizError(AuthErr.OAUTH_EMAIL_TAKEN, "This Github account is already bound to another user")

    user = await get_or_raise(db, User, AuthErr.USER_NOT_FOUND, User.id == user_id)

    db.add(
        UserOAuth(
            user_id=int(user.id),  # type: ignore[arg-type]
            provider="github",
            provider_user_id=gh_user["provider_user_id"],
            provider_email=gh_user["provider_email"],
        )
    )
    await db.flush()

    await upgrade_to_normal(db, user)  # type: ignore[arg-type]

    return {"message": "Github account bound"}
