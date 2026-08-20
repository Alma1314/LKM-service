from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models import BlogContent, BlogSeries
from app.modules.blog import backfill


class _FakeGit:
    """替身：把内存 dict 当仓库文件表，记下被读过的路径。"""
    def __init__(self, files: dict[str, str]):
        self.files = dict(files)
        self.reads: list[str] = []

    def revparse_or_none(self, repo_name: str):
        return "new"

    def diff_tree_names(self, repo_name, old_sha, new_sha):
        return list(self.files)

    def read_file(self, repo_name, path):
        self.reads.append(path)
        return self.files[path]


@pytest.fixture
def fake_git(monkeypatch):
    fg = _FakeGit({"a.md": "# a", "b.md": "# b"})
    monkeypatch.setattr(backfill.git_svc, "revparse_or_none", fg.revparse_or_none)
    monkeypatch.setattr(backfill.git_svc, "diff_tree_names", fg.diff_tree_names)
    monkeypatch.setattr(backfill.git_svc, "read_file", fg.read_file)
    return fg


@pytest.fixture
async def series(db):
    s = BlogSeries(
        owner_id=1, title="t", repo_name="repo-standard", description=None
    )
    db.add(s)
    await db.flush()
    await db.refresh(s)
    return s.id


def _t(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=UTC)


async def test_backfill_inserts_new_files(db, fake_git, series):
    # 空表：全部 upsert
    res = await backfill.backfill_series_from_git(
        db, "repo-standard", series, None, push_at=_t(2026, 8, 20, 4, 0, 0)
    )
    assert set(res.upserted) == {"a.md", "b.md"}
    assert res.skipped == []
    assert set(res.paths) == {"a.md", "b.md"}


async def test_backfill_skips_when_db_newer(db, fake_git, series):
    db.add(
        BlogContent(
            series_id=series, path="a.md", content="NEWER", sha3="x", version=5,
            updated_at=_t(2026, 8, 20, 23, 0, 0),  # 比 push 时刻更新
        )
    )
    await db.flush()

    res = await backfill.backfill_series_from_git(
        db, "repo-standard", series, None, push_at=_t(2026, 8, 20, 4, 0, 0)
    )
    assert "a.md" in res.skipped
    # DB 更新的不覆盖
    existing = (
        (await db.execute(select(BlogContent).where(BlogContent.path == "a.md")))
        .scalars()
        .first()
    )
    assert existing.content == "NEWER"
    assert "b.md" in res.upserted


async def test_backfill_overwrites_when_push_newer(db, fake_git, series):
    db.add(
        BlogContent(
            series_id=series, path="a.md", content="OLD", sha3="x", version=1,
            updated_at=_t(2026, 8, 1, 0, 0, 0),  # 早于 push
        )
    )
    await db.flush()

    res = await backfill.backfill_series_from_git(
        db, "repo-standard", series, None, push_at=_t(2026, 8, 20, 4, 0, 0)
    )
    assert "a.md" in res.upserted
    existing = (
        (await db.execute(select(BlogContent).where(BlogContent.path == "a.md")))
        .scalars()
        .first()
    )
    assert existing.content == "# a"
    assert existing.version == 2  # 递增
