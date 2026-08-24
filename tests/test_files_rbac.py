"""files 迁移 RBAC：上传/下载/审核/属主。

测试约定（与 test_columns_rbac 同款）：
- 用 conftest 的 db / client fixture。
- _mk_user 的 hashed_password 填占位非空；Profile 列是 nickname（非 display_name）。
- create_access_token 的 role 为必填。
- 上传端点走 multipart，且 create_file 需落盘，故涉上传用例需把 files_store_dir 指到 tmp_path。
"""

import io

from app.db.models import Profile, RolePermission, User
from app.modules.auth.security import create_access_token
from tests.conftest import DB, Client


async def _mk_user(
    db: DB, uname: str, level: str = "normal", role: str = "member"
) -> User:
    # hashed_password 为 NOT NULL；Profile 列是 nickname。
    u = User(
        username=uname,
        account_level=level,
        hashed_password="rbac-test-placeholder-not-a-real-hash",
    )
    db.add(u)
    await db.flush()
    db.add(Profile(user_id=u.id, role=role, nickname=uname))
    await db.flush()
    return u


def _h(u: User, role: str = "member") -> dict[str, str]:
    tok = create_access_token(user_id=u.id, account_level=u.account_level, role=role)
    return {"Authorization": f"Bearer {tok}"}


def _admin_h(u: User, role: str = "super_admin") -> dict[str, str]:
    # role 直接传，避让 u.profile 惰性加载（fresh session 外会 MissingGreenlet）
    return _h(u, role=role)


async def _grant(db: DB, role_name: str, *perms: str) -> None:
    for p in perms:
        db.add(RolePermission(role_name=role_name, permission=p))
    await db.flush()


async def _upload(
    client: Client, headers: dict[str, str], original_name: str = "讲义.pdf"
):
    return await client.post(
        "/api/v1/files",
        headers=headers,
        files={
            "file": (
                original_name,
                io.BytesIO(b"%PDF-1.4 content"),
                "application/pdf",
            )
        },
        data={"category_id": "math", "description": "rbac 测试", "tags": "[]"},
    )


async def _mk_file(
    db: DB,
    client: Client,
    tmp_path,
    monkeypatch,
    uploader: User,
    approved: bool = False,
) -> int:
    """造一个文件：先以 uploader 上传，再（可选）由 super_admin 审核通过。

    需把 files_store_dir 指到 tmp_path 使落盘可用。
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
    await _grant(db, "normal:member", "files.upload")
    r = await _upload(client, _h(uploader))
    assert r.status_code == 200, r.text
    fid = r.json()["data"]["id"]
    if approved:
        sa = await _mk_user(db, "sa_review", level="admin", role="super_admin")
        await _grant(db, "admin:super_admin", "files.review")
        rr = await client.post(
            f"/api/v1/files/{fid}/review",
            headers=_admin_h(sa),
            data={"status": "approved"},
        )
        assert rr.status_code == 200, rr.text
    return fid


# ---- 上传 ----


async def test_upload_without_auth_is_403(db: DB, client: Client) -> None:
    await _mk_user(db, "u_noauth")
    r = await client.post(
        "/api/v1/files",
        files={"file": ("a.pdf", io.BytesIO(b"content"), "application/pdf")},
    )
    # get_current_user 必选 → 无 Authorization 头 403
    assert r.status_code == 403


async def test_member_without_upload_perm_is_403(
    db: DB, client: Client, tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
    # member 未授 files.upload（默认 normal:member 不授）
    u = await _mk_user(db, "u_noperm", level="normal", role="member")
    r = await _upload(client, _h(u))
    # 迁移后：RequirePermission(files.upload) → 403
    assert r.status_code == 403


async def test_member_with_upload_perm_can_upload(
    db: DB, client: Client, tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
    await _grant(db, "normal:member", "files.upload")
    u = await _mk_user(db, "u_ok", level="normal", role="member")
    r = await _upload(client, _h(u))
    assert r.status_code == 200
    assert r.json()["data"]["uploader_id"] == u.id


# ---- 下载 ----


async def test_download_without_perm_is_403(
    db: DB, client: Client, tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
    uploader = await _mk_user(db, "dl_owner", level="normal", role="member")
    fid = await _mk_file(db, client, tmp_path, monkeypatch, uploader, approved=True)
    # 下载者未授 files.download（不设权限 / 只授 upload）
    actor = await _mk_user(db, "dl_noperm", level="normal", role="member")
    r = await client.post(f"/api/v1/files/{fid}/download", headers=_h(actor))
    assert r.status_code == 403


async def test_download_with_perm_is_200(
    db: DB, client: Client, tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
    uploader = await _mk_user(db, "dl2_owner", level="normal", role="member")
    fid = await _mk_file(db, client, tmp_path, monkeypatch, uploader, approved=True)
    await _grant(db, "normal:member", "files.download")
    actor = await _mk_user(db, "dl2_ok", level="normal", role="member")
    r = await client.post(f"/api/v1/files/{fid}/download", headers=_h(actor))
    assert r.status_code == 200


# ---- 删除（属主 / 代管） ----


async def test_delete_others_file_is_403(
    db: DB, client: Client, tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
    owner = await _mk_user(db, "del_owner", level="normal", role="member")
    fid = await _mk_file(db, client, tmp_path, monkeypatch, owner)
    other = await _mk_user(db, "del_other", level="normal", role="member")
    r = await client.post(f"/api/v1/files/{fid}/delete", headers=_h(other))
    assert r.status_code == 403


async def test_delete_own_file_is_200(
    db: DB, client: Client, tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
    owner = await _mk_user(db, "del_self", level="normal", role="member")
    fid = await _mk_file(db, client, tmp_path, monkeypatch, owner)
    r = await client.post(f"/api/v1/files/{fid}/delete", headers=_h(owner))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "deleted"


async def test_super_admin_can_delete_others_file(
    db: DB, client: Client, tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "files_store_dir", str(tmp_path))
    owner = await _mk_user(db, "del_sa_owner", level="normal", role="member")
    fid = await _mk_file(db, client, tmp_path, monkeypatch, owner)
    sa = await _mk_user(db, "del_sa", level="admin", role="super_admin")
    # super_admin 授 file.owner_delete → check_owner 凭 owner 权限点代管放行
    await _grant(db, "admin:super_admin", "file.owner_delete")
    r = await client.post(f"/api/v1/files/{fid}/delete", headers=_admin_h(sa))
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "deleted"
