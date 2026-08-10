import pytest

from app.core.err import BizError, ErrCode
from app.modules.members.service import get_members


class TestMembersService:
    """Service 层：直接测试 get_members() 业务逻辑。"""

    # -- memberLists 查询 --

    def test_founder_members(self):
        r = get_members("founderMembers")
        assert len(r.items) == 1
        assert r.items[0].name == "可琪（若有千寻）"
        assert r.items[0].role == "创始人"

    def test_general_members(self):
        r = get_members("generalMembers")
        assert len(r.items) == 7

    def test_events_members(self):
        r = get_members("eventsMembers")
        assert len(r.items) == 1
        assert r.items[0].name == "七月赤"

    def test_news_members_is_empty(self):
        r = get_members("newsMembers")
        assert r.items == []

    def test_advisor_members(self):
        r = get_members("advisorMembers")
        assert len(r.items) == 1
        assert r.items[0].role == "团长"

    def test_tech_members(self):
        r = get_members("techMembers")
        assert len(r.items) == 3

    def test_alumni_members(self):
        r = get_members("alumniMembers")
        assert len(r.items) == 27

    # -- subGroupMaps 指定子组 --

    def test_project_sub_group_textbooks(self):
        r = get_members("projectSubGroups", "textbooks")
        assert len(r.items) == 3
        names = {m.name for m in r.items}
        assert "七月大雄" in names

    def test_project_sub_group_science_empty(self):
        r = get_members("projectSubGroups", "science")
        assert r.items == []

    def test_news_sub_group_production(self):
        r = get_members("newsSubGroups", "production")
        assert len(r.items) == 3
        names = {m.name for m in r.items}
        assert "七月一前" in names

    def test_news_sub_group_promotion_empty(self):
        r = get_members("newsSubGroups", "promotion")
        assert r.items == []

    def test_professional_math(self):
        r = get_members("professionalSubGroups", "math")
        assert len(r.items) == 6

    def test_affairs_high(self):
        r = get_members("affairsSubGroups", "high")
        assert len(r.items) == 6

    # -- subGroupMaps 不指定子组（汇总） --

    def test_affairs_sub_groups_all(self):
        r = get_members("affairsSubGroups")
        assert len(r.items) == 16

    def test_project_sub_groups_all(self):
        r = get_members("projectSubGroups")
        assert len(r.items) == 3

    # -- 错误路径 --

    def test_unknown_type_raises_biz_error(self):
        with pytest.raises(BizError) as exc:
            get_members("noSuchType")
        assert exc.value.errcode == ErrCode.MEMBER_GROUP_NOT_FOUND

    def test_unknown_group_raises_biz_error(self):
        with pytest.raises(BizError) as exc:
            get_members("projectSubGroups", "noSuchGroup")
        assert exc.value.errcode == ErrCode.MEMBER_GROUP_NOT_FOUND

    # -- 字段可选性 --

    def test_member_with_minimal_fields(self):
        """七月爱畅依间只有 name + avatarKey。"""
        r = get_members("affairsSubGroups", "high")
        m = next(m for m in r.items if m.name == "七月爱畅依间")
        assert m.name == "七月爱畅依间"
        assert m.avatarKey == "七月爱畅依间.jpeg"
        assert m.role is None
        assert m.desc is None
        assert m.dream is None
        assert m.quote is None

    def test_member_with_only_name_and_role(self):
        """alumni 中七月丫只有 name + role。"""
        r = get_members("alumniMembers")
        m = next(m for m in r.items if m.name == "七月丫")
        assert m.role == "组长"
        assert m.avatarKey is None

    def test_member_without_avatar_key(self):
        """七月雨夜 avatarKey 被注释掉（TS 中），应为 None。"""
        r = get_members("professionalSubGroups", "medicine")
        m = r.items[0]
        assert m.name == "七月雨夜"
        assert m.avatarKey is None


class TestMembersRoutes:
    """HTTP 层：测试 /api/v1/members 端点。client 由 tests/conftest.py 提供。"""

    async def test_get_founder_members(self, client):
        resp = await client.get("/api/v1/members?type=founderMembers")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["name"] == "可琪（若有千寻）"

    async def test_get_project_sub_group(self, client):
        resp = await client.get("/api/v1/members?type=projectSubGroups&group=textbooks")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 3

    async def test_unknown_type_returns_404(self, client):
        resp = await client.get("/api/v1/members?type=noSuchType")
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == ErrCode.MEMBER_GROUP_NOT_FOUND

    async def test_unknown_group_returns_404(self, client):
        resp = await client.get("/api/v1/members?type=projectSubGroups&group=noSuchGroup")
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == ErrCode.MEMBER_GROUP_NOT_FOUND

    async def test_missing_type_returns_422(self, client):
        resp = await client.get("/api/v1/members")
        assert resp.status_code == 422

    async def test_response_structure(self, client):
        """验证 ApiResp + ListData 包装结构。"""
        resp = await client.get("/api/v1/members?type=techMembers")
        body = resp.json()
        assert "code" in body
        assert "msg" in body
        assert "data" in body
        assert "items" in body["data"]

    async def test_get_subgroups_project(self, client):
        """验证 /api/v1/members/subgroups 返回完整分组结构。"""
        resp = await client.get("/api/v1/members/subgroups?type=projectSubGroups")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        groups = body["data"]["items"]
        assert len(groups) == 2
        textbooks = next(g for g in groups if g["key"] == "textbooks")
        assert textbooks["label"] == "教材项目组"
        assert textbooks["desc"]
        assert len(textbooks["members"]) == 3
        assert "key" in textbooks

    async def test_get_subgroups_unknown_returns_404(self, client):
        resp = await client.get("/api/v1/members/subgroups?type=noSuchType")
        assert resp.status_code == 404
        assert resp.json()["code"] == ErrCode.MEMBER_GROUP_NOT_FOUND

    async def test_get_subgroups_missing_type_returns_422(self, client):
        resp = await client.get("/api/v1/members/subgroups")
        assert resp.status_code == 422
