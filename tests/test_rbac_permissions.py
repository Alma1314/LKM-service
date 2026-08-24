"""权限点枚举与复合角色基础测试。"""

from app.modules.rbac.permissions import (
    DEFAULT_GRANTS,
    Permission,
    composible_role,
)


def test_composite_role() -> None:
    assert composible_role("admin", "super_admin") == "admin:super_admin"
    assert composible_role("normal", "member") == "normal:member"
    assert composible_role("local", "member") == "local:member"


def test_permission_values_are_two_segment() -> None:
    for p in Permission:
        segments = p.value.split(".")
        assert len(segments) == 2, f"{p.value} 非两段式"


def test_default_grants_cover_all_permissions() -> None:
    covered: set[str] = set()
    for grants in DEFAULT_GRANTS.values():
        for g in grants:
            covered.add(g.permission.value)
    for p in Permission:
        assert p.value in covered, f"{p.value} 未在 DEFAULT_GRANTS 中被任何角色授予"


def test_super_admin_has_admin_content_review() -> None:
    perms = {g.permission for g in DEFAULT_GRANTS["admin:super_admin"]}
    assert Permission.admin_content_review in perms
