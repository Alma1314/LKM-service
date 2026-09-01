import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.blog import git_svc
from app.modules.blog import tasks as reconcile_blog_repos
from app.modules.blog.models import BlogRepoQuarantine


@pytest.fixture
def repo_dir(monkeypatch, tmp_path):
    from app.core.config import settings

    p = str(tmp_path / "blog_repos")
    monkeypatch.setattr(settings, "blog_repo_dir", p)
    os.makedirs(p, exist_ok=True)
    return p


async def _no_redis():
    """fake get_redis：返回 None，跳过 Redis 锁（与生产同为 awaitable 契约）。"""
    return None


async def _factory(db):
    """fake session factory：返回注入的内存会话（与生产 new_session 同为 async 契约）。"""
    return db


@pytest.fixture
def inject_session(monkeypatch, db):
    """让任务用 conftest 的内存会话，并跳过 Redis 锁。"""
    monkeypatch.setattr(reconcile_blog_repos, "_session_factory", lambda: _factory(db))
    monkeypatch.setattr(reconcile_blog_repos, "get_redis", _no_redis)


def _mk_repo(repo_dir, name):
    git_svc.init_bare_repo(name)


async def test_quarantine_new_orphan(db, repo_dir, inject_session):
    _mk_repo(repo_dir, "orphan1")  # 无 blog_series 记录

    await reconcile_blog_repos.reconcile_blog_repos()

    rows = (await db.execute(select(BlogRepoQuarantine))).scalars().all()
    assert len(rows) == 1
    assert rows[0].repo_name == "orphan1"
    assert os.path.isdir(f"{repo_dir}/orphan1.git")  # noqa: ASYNC240 目录不动


async def test_delete_quarantined_after_grace(db, repo_dir, inject_session):
    _mk_repo(repo_dir, "orphan2")
    # 预置一条超龄隔离
    db.add(
        BlogRepoQuarantine(
            repo_name="orphan2",
            src_dir=f"{repo_dir}/orphan2.git",
            quarantined_at=datetime.now(UTC) - timedelta(days=14),
        )
    )
    await db.flush()

    await reconcile_blog_repos.reconcile_blog_repos()

    # 已物理删除
    assert not os.path.exists(f"{repo_dir}/orphan2.git")  # noqa: ASYNC240
    rows = (await db.execute(select(BlogRepoQuarantine))).scalars().all()
    assert rows == []


async def test_skip_when_series_exists(db, repo_dir, inject_session):
    from app.modules.blog.models import BlogSeries

    _mk_repo(repo_dir, "live")
    db.add(BlogSeries(owner_id=1, title="t", repo_name="live"))
    await db.flush()

    await reconcile_blog_repos.reconcile_blog_repos()

    assert (await db.execute(select(BlogRepoQuarantine))).scalars().all() == []
    assert os.path.isdir(f"{repo_dir}/live.git")  # noqa: ASYNC240
