"""Github OAuth 服务 —— 授权 URL、处理回调、绑定账户。"""

import datetime as dt
import secrets

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.err import BizError, ErrCode
from app.db.models import Profile, User
from app.modules.auth.models import OAuthState, TOTP, UserOAuth
from app.modules.auth.service_auth import _create_auth_response, log_audit, upgrade_to_normal


def _generate_oauth_state(db: Session, purpose: str) -> str:
    """生成一个高熵的 OAuth state 令牌，存储并返回它。"""
    state = secrets.token_urlsafe(32)
    expires_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)).isoformat()
    db.add(OAuthState(state=state, purpose=purpose, expires_at=expires_at))
    db.flush()
    return state


def _consume_oauth_state(db: Session, state: str, purpose: str) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    result = db.execute(
        text(
            "UPDATE oauth_states SET consumed = 1 "
            "WHERE state = :st AND consumed = 0 AND purpose = :purpose "
            "AND expires_at > :now"
        ),
        {"st": state, "purpose": purpose, "now": now},
    )
    if result.rowcount != 1:  # pyright: ignore[reportAttributeAccessIssue]
        raise BizError(ErrCode.OAUTH_PROVIDER_ERROR, "Invalid or expired OAuth state")


def get_github_auth_url(db: Session, purpose: str = "login") -> str:
    state = _generate_oauth_state(db, purpose)
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
            raise BizError(ErrCode.OAUTH_PROVIDER_ERROR, data.get("error_description", "No access token"))
        return access_token


async def _get_github_user(access_token: str) -> dict:
    """获取 GitHub 用户资料和主邮箱。"""
    headers = {"Authorization": f"token {access_token}"}
    async with httpx.AsyncClient() as client:
        # 获取用户资料
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        user_data = user_resp.json()
        if "id" not in user_data:
            raise BizError(ErrCode.OAUTH_PROVIDER_ERROR, "Failed to fetch GitHub user")

        # 获取邮箱列表
        emails_resp = await client.get("https://api.github.com/user/emails", headers=headers)
        emails_data = emails_resp.json()
        primary_email = None
        if isinstance(emails_data, list):
            for entry in emails_data:
                if entry.get("primary") and entry.get("verified"):
                    primary_email = entry["email"]
                    break
            # 备选方案：第一个已验证的邮箱
            if primary_email is None:
                for entry in emails_data:
                    if entry.get("verified"):
                        primary_email = entry["email"]
                        break

        return {
            "provider_user_id": str(user_data["id"]),
            "provider_email": primary_email,
            "login": user_data.get("login", ""),
        }


async def handle_github_callback(db: Session, code: str, state: str) -> dict:
    _consume_oauth_state(db, state, "login")
    access_token = await _exchange_github_token(code)
    gh_user = await _get_github_user(access_token)

    # 1. 现有 OAuth 绑定
    oauth = (
        db.query(UserOAuth)
        .filter(
            UserOAuth.provider == "github",
            UserOAuth.provider_user_id == gh_user["provider_user_id"],
        )
        .first()
    )
    if oauth:
        user = db.query(User).filter(User.id == oauth.user_id).first()
        if not user:
            raise BizError(ErrCode.USER_NOT_FOUND)
        return _oauth_login_response(db, user)

    # 2. 通过邮箱查找现有用户 -> 绑定
    if gh_user["provider_email"]:
        user = db.query(User).filter(User.email == gh_user["provider_email"]).first()
        if user:
            db.add(
                UserOAuth(
                    user_id=user.id,
                    provider="github",
                    provider_user_id=gh_user["provider_user_id"],
                    provider_email=gh_user["provider_email"],
                )
            )
            db.flush()
            upgrade_to_normal(db, user)
            return _oauth_login_response(db, user)

    # 3. 创建新用户
    username = gh_user["login"]
    # 确保唯一性
    suffix = 1
    base = username
    while db.query(User).filter(User.username == username).first():
        username = f"{base}{suffix}"
        suffix += 1

    user = User(
        username=username,
        email=gh_user["provider_email"],
        hashed_password="",
        account_level="normal",
    )
    db.add(user)
    db.flush()

    db.add(Profile(user_id=user.id, role="member"))
    db.flush()

    db.add(
        UserOAuth(
            user_id=user.id,
            provider="github",
            provider_user_id=gh_user["provider_user_id"],
            provider_email=gh_user["provider_email"],
        )
    )
    db.flush()

    log_audit(db, user.id, "oauth_login", "github")

    return _oauth_login_response(db, user)


def _oauth_login_response(db: Session, user: User) -> dict:
    """检查 TOTP 要求并返回认证响应。"""
    from app.modules.auth.security import create_temp_token

    # 没有 TOTP 的管理员 —— 发放设置令牌（与 login_password 相同的模式）
    if user.account_level == "admin":
        totp = db.query(TOTP).filter(TOTP.user_id == user.id).first()
        if not totp or not totp.enabled:
            setup_token = create_temp_token(user.id, purpose="setup")
            return {
                "access_token": None,
                "refresh_token": None,
                "user_id": user.id,
                "account_level": user.account_level,
                "requires_2fa": True,
                "setup_required": True,
                "temp_token": setup_token,
            }

    # 检查 2FA
    requires_2fa = False
    if user.account_level in ("normal", "admin"):
        totp = db.query(TOTP).filter(
            TOTP.user_id == user.id, TOTP.enabled.is_(True)
        ).first()
        if totp:
            requires_2fa = True

    return _create_auth_response(db, user, requires_2fa=requires_2fa)


async def bind_github(db: Session, user_id: int, code: str, state: str) -> dict:
    _consume_oauth_state(db, state, "bind")
    access_token = await _exchange_github_token(code)
    gh_user = await _get_github_user(access_token)

    existing_oauth = (
        db.query(UserOAuth)
        .filter(
            UserOAuth.provider == "github",
            UserOAuth.provider_user_id == gh_user["provider_user_id"],
        )
        .first()
    )
    if existing_oauth:
        raise BizError(ErrCode.OAUTH_EMAIL_TAKEN, "This Github account is already bound to another user")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise BizError(ErrCode.USER_NOT_FOUND)

    db.add(
        UserOAuth(
            user_id=user.id,
            provider="github",
            provider_user_id=gh_user["provider_user_id"],
            provider_email=gh_user["provider_email"],
        )
    )
    db.flush()

    upgrade_to_normal(db, user)

    return {"message": "Github account bound"}
