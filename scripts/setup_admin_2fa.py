"""临时脚本：给指定 admin 启用 TOTP，并打印当前一次性验证码（供 step-up 链路验证用）。

用法： python scripts/setup_admin_2fa.py <username>
仅用于验证 2FA step-up 流程，执行后销毁。
"""

import asyncio
import base64
import sys

from sqlalchemy import select

from app.db.models import User
from app.db.session import dispose_engine, get_async_engine, new_session
from app.modules.auth import service_2fa
from app.modules.auth.security import _totp_code, _totp_now


def current_code(secret: str) -> str:
    key = base64.b32decode(secret, casefold=True)
    return _totp_code(key, _totp_now())


async def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else "alma"
    get_async_engine()
    db = await new_session()
    try:
        user = (
            (await db.execute(select(User).where(User.username == username)))
            .scalars()
            .first()
        )
        if user is None:
            print("[skip] 用户不存在")
            return
        begin = await service_2fa.setup_2fa_begin(db, user.id)
        secret = begin["secret"]
        code = current_code(secret)
        res = await service_2fa.setup_2fa_complete(db, user.id, code)
        await db.commit()
        print(f"SECRET={secret}")
        print(f"CURRENT_CODE={code}")
        print(f"RECOVERY={','.join(res['recovery_codes'])}")
    finally:
        await db.close()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
