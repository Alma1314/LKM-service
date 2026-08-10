"""Github OAuth 路由 – 登录重定向、回调、绑定。"""

from urllib.parse import urlencode
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.err import BizError, respond
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.auth import service_oauth
from app.modules.auth.schemas import OAuthRedirectResponse
from app.modules.common import ApiResp

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])


@router.get("/github/login")
def github_login(db: Session = Depends(get_session)):
    """将用户重定向到 Github OAuth 授权页面。"""
    url = service_oauth.get_github_auth_url(db, purpose="login")
    return RedirectResponse(url=url)


@router.get("/github/callback")
async def github_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_session),
):
    """处理 Github OAuth 登录回调，302 到前端并携带会话令牌（或 2FA 的 temp_token）。

    令牌通过 URL fragment（#access_token=...）而非 query（?access_token=...）回传，
    避免令牌进入浏览器历史、代理与日志（官方推荐方式）。前端需从 location.hash 解析。
    """
    result = await service_oauth.handle_github_callback(db, code, state)
    params: dict[str, Any] = {
        "access_token": result.get("access_token") or "",
        "refresh_token": result.get("refresh_token") or "",
        "temp_token": result.get("temp_token") or "",
        "requires_2fa": "true" if result.get("requires_2fa") else "false",
        "setup_required": "true" if result.get("setup_required") else "false",
    }
    clean: dict[str, Any] = {k: v for k, v in params.items() if v != ""}
    frag = urlencode(clean)
    url = f"{settings.frontend_callback}#{frag}" if frag else settings.frontend_callback
    return RedirectResponse(url=url)


@router.post("/github/login/redirect", response_model=ApiResp[OAuthRedirectResponse])
@respond
def github_bind_redirect(cur: CurrentUser = Depends(get_current_user), db: Session = Depends(get_session)):
    """返回用于绑定的 OAuth 授权 URL（从 JS 客户端调用）。将发起用户写入 OAuth state。"""
    url = service_oauth.get_github_auth_url(db, purpose="bind", user_id=cur.id)
    return {"url": url}


@router.get("/github/bind-callback")
async def github_bind_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_session),
):
    """处理绑定 Github OAuth 回调：302 到前端携带结果（无需 header JWT，归属由 state 记录决定）。

    与登录回调一致，结果经 URL fragment（#success=...）而非 query 回传，
    避免进入浏览器历史与日志；前端从 location.hash 解析即可。
    """
    try:
        await service_oauth.bind_github(db, code, state)
        frag = urlencode({"success": "1", "message": "Github account bound"})
    except BizError as exc:
        frag = urlencode({"success": "0", "error": exc.errcode.name, "message": str(exc.detail or "")})
    return RedirectResponse(url=f"{settings.frontend_callback}#{frag}")
