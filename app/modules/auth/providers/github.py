"""Github OAuth 实现。"""

from typing import Any, cast

import httpx

from app.core.config import settings
from app.core.err import BizError
from app.modules.auth.errors import AuthErr
from app.modules.auth.providers.oauth import OAuthUserInfo, register_provider


class GithubOAuth:
    name: str = "github"

    def authorize_url(self, state: str) -> str:
        return (
            f"https://github.com/login/oauth/authorize"
            f"?client_id={settings.github_client_id}"
            f"&redirect_uri={settings.github_redirect_uri}"
            f"&scope=user:email"
            f"&state={state}"
        )

    async def exchange_code(self, code: str) -> str:
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
                raise BizError(
                    AuthErr.OAUTH_PROVIDER_ERROR,
                    data.get("error_description", "No access token"),
                )
            return access_token

    async def fetch_user(self, access_token: str) -> OAuthUserInfo:
        """获取 GitHub 用户资料和主邮箱。"""
        headers = {"Authorization": f"token {access_token}"}
        async with httpx.AsyncClient() as client:
            user_resp = await client.get("https://api.github.com/user", headers=headers)
            user_data = user_resp.json()
            if "id" not in user_data:
                raise BizError(
                    AuthErr.OAUTH_PROVIDER_ERROR, "Failed to fetch GitHub user"
                )

            emails_resp = await client.get(
                "https://api.github.com/user/emails", headers=headers
            )
            emails_data = emails_resp.json()
            primary_email: str | None = None
            if isinstance(emails_data, list):
                entries = cast(list[Any], emails_data)
                for entry in entries:
                    if entry.get("primary") and entry.get("verified"):
                        primary_email = entry["email"]
                        break
                if primary_email is None:
                    for entry in entries:
                        if entry.get("verified"):
                            primary_email = entry["email"]
                            break

            return OAuthUserInfo(
                provider_user_id=str(user_data["id"]),
                provider_email=primary_email,
                username=user_data.get("login", ""),
            )


register_provider(GithubOAuth())
