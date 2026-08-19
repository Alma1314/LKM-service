import asyncio
import os
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.err import BizError, CommonErr
from app.modules.auth.schemas import ProfileUpdate
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.auth.service import update_profile
from app.modules.blog.errors import BlogErr
from app.modules.blog.models import BlogSeriesStatus
from app.modules.blog.schemas import (
    BlogCommentCreate,
    BlogSeriesCreate,
    BlogSeriesInfo,
    BlogSeriesUpdate,
)
from app.modules.blog.service import (
    create_comment,
    create_series,
    delete_comment,
    delete_series,
    get_file_content,
    get_series,
    list_comments,
    list_series,
    toggle_star,
    update_series,
)

# ---- fixtures ----
# db 与 client fixture 均由 tests/conftest.py 提供（内存 sqlite 会话 + httpx.AsyncClient）


@pytest.fixture
def blog_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[str]:
    path = str(tmp_path / "blog_repos")
    monkeypatch.setattr(settings, "blog_repo_dir", path)
    yield path
    monkeypatch.setattr(settings, "blog_repo_dir", "blog_repos")


# ---- helpers ----


async def _user(
    db: AsyncSession, username: str = "alice", email: str = "alice@example.com"
) -> int:
    from app.db.models import Profile, User

    user = User(
        username=username,
        email=email,
        hashed_password=await hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id))
    await db.flush()
    return user.id


async def _series(
    db: AsyncSession, user_id: int = 1, repo_name: str = "my-blog"
) -> BlogSeriesInfo:
    return await create_series(
        db,
        user_id,
        BlogSeriesCreate(
            title="My Blog", description="A test blog series", repo_name=repo_name
        ),
    )


def _seed_bare_repo(repo_dir: str, repo_name: str, files: dict[str, str]) -> None:
    """Seed a bare git repo with files using git plumbing commands."""
    bare = os.path.join(repo_dir, f"{repo_name}.git")

    def _git(*args: str, stdin: bytes = b"") -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "--git-dir", bare, *list(args)],
            input=stdin,
            capture_output=True,
            check=True,
        )
        return subprocess.run(
            ["git", "--git-dir", bare, *list(args)],
            input=stdin,
            capture_output=True,
            check=True,
        )

    # hash all files
    blob_hashes: dict[str, str] = {}
    for fpath, content in files.items():
        blob_hashes[fpath] = (
            _git("hash-object", "-w", "--stdin", stdin=content.encode())
            .stdout.decode()
            .strip()
        )

    # group files by their parent directory (root "" always present)
    dir_contents: dict[str, list[str]] = {"": []}
    for fpath in sorted(files):
        parts = fpath.split("/")
        dname = "/".join(parts[:-1]) if len(parts) > 1 else ""
        fname = parts[-1]
        h = blob_hashes[fpath]
        dir_contents.setdefault(dname, []).append(f"100644 blob {h}\t{fname}")

    # build trees from deepest to shallowest
    sorted_dirs = sorted(dir_contents.keys(), key=lambda d: (-d.count("/"), d == ""))
    trees: dict[str, str] = {}

    for d in sorted_dirs:
        entries = list(dir_contents[d])
        # fold child trees into parent
        prefix = d + "/" if d else ""
        for child_dir, child_tree in sorted(trees.items()):
            if child_dir.startswith(prefix):
                rel = child_dir[len(prefix) :]
                if "/" not in rel:
                    entries.append(f"040000 tree {child_tree}\t{rel}")
        tree_hash = (
            _git("mktree", stdin="\n".join(entries).encode()).stdout.decode().strip()
        )
        trees[d] = tree_hash

    root_tree = trees.get("", "")
    commit = (
        _git("commit-tree", root_tree, "-m", "initial commit").stdout.decode().strip()
    )
    _git("update-ref", "refs/heads/master", commit)


# ---- series CRUD ----


class TestBlogSeries:
    async def should_create_series(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        assert series.id == 1
        assert series.owner_id == user_id
        assert series.title == "My Blog"
        assert series.status == BlogSeriesStatus.ACTIVE
        assert series.star_count == 0
        assert not series.is_starred
        # verify bare repo on disk
        assert await asyncio.to_thread(
            os.path.isdir, os.path.join(blog_dir, "my-blog.git")
        )

    async def should_reject_duplicate_repo_name(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        await _user(db)
        await _series(db, repo_name="taken")

        with pytest.raises(BizError) as exc:
            await _series(db, repo_name="taken")

        assert exc.value.errcode == CommonErr.INVALID_INPUT

    async def should_list_series(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        await _series(db, user_id=user_id, repo_name="blog-a")
        await _series(db, user_id=user_id, repo_name="blog-b")

        items = await list_series(db)
        assert len(items) == 2

    async def should_list_series_with_star_info(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        await toggle_star(db, series.id, user_id)
        items = await list_series(db, current_user_id=user_id)
        assert items[0].star_count == 1
        assert items[0].is_starred

    async def should_list_series_guest(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        await toggle_star(db, series.id, user_id)
        items = await list_series(db, current_user_id=None)
        assert items[0].star_count == 1
        assert not items[0].is_starred

    async def should_get_series(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        detail = await get_series(db, series.id)
        assert detail.id == series.id
        assert detail.file_tree is None  # empty repo

    async def should_get_series_with_file_tree(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        _seed_bare_repo(
            blog_dir,
            "my-blog",
            {"README.md": "# Hello", "posts/2026-01-01.md": "# Post"},
        )

        detail = await get_series(db, series.id)
        assert detail.file_tree is not None
        assert len(detail.file_tree) == 2  # README.md + posts/

    async def should_reject_nonexistent_series(self, db: AsyncSession) -> None:
        with pytest.raises(BizError) as exc:
            await get_series(db, 999)

        assert exc.value.errcode == BlogErr.SERIES_NOT_FOUND

    async def should_update_series(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        updated = await update_series(
            db,
            series.id,
            user_id,
            BlogSeriesUpdate(title="New Title", description="New desc"),
        )
        assert updated.title == "New Title"
        assert updated.description == "New desc"

    async def should_reject_update_by_non_owner(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        other = await _user(db, username="bob", email="bob@bob.com")
        series = await _series(db, user_id=user_id)

        with pytest.raises(BizError) as exc:
            await update_series(db, series.id, other, BlogSeriesUpdate(title="Bad!"))

        assert exc.value.errcode == CommonErr.FORBIDDEN

    async def should_delete_series(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        await delete_series(db, series.id, user_id)

        with pytest.raises(BizError) as exc:
            await get_series(db, series.id)
        assert exc.value.errcode == BlogErr.SERIES_NOT_FOUND
        # repo physically removed
        assert not await asyncio.to_thread(
            os.path.exists, os.path.join(blog_dir, "my-blog.git")
        )

    async def should_reject_delete_by_non_owner(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        other = await _user(db, username="bob", email="bob@bob.com")
        series = await _series(db, user_id=user_id)

        with pytest.raises(BizError) as exc:
            await delete_series(db, series.id, other)

        assert exc.value.errcode == CommonErr.FORBIDDEN


# ---- stars ----


class TestBlogStars:
    async def should_star_and_unstar(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        result = await toggle_star(db, series.id, user_id)
        assert result.starred
        assert result.star_count == 1

        result = await toggle_star(db, series.id, user_id)
        assert not result.starred
        assert result.star_count == 0

    async def should_reject_star_nonexistent_series(self, db: AsyncSession) -> None:
        with pytest.raises(BizError) as exc:
            await toggle_star(db, 999, 1)
        assert exc.value.errcode == BlogErr.SERIES_NOT_FOUND

    async def should_count_stars_correctly(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        other = await _user(db, username="bob", email="bob@bob.com")
        series = await _series(db, user_id=user_id)

        await toggle_star(db, series.id, user_id)
        await toggle_star(db, series.id, other)

        items = await list_series(db)
        assert items[0].star_count == 2


# ---- comments ----


class TestBlogComments:
    async def should_create_comment(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        comment = await create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Nice post!")
        )
        assert comment.id == 1
        assert comment.content == "Nice post!"
        assert comment.parent_id is None
        assert comment.replies == []

    async def should_create_reply(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)
        parent = await create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Root")
        )

        reply = await create_comment(
            db,
            series.id,
            user_id,
            BlogCommentCreate(content="Reply", parent_id=parent.id),
        )
        assert reply.parent_id == parent.id

    async def should_list_threaded_comments(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        c1 = await create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Comment 1")
        )
        await create_comment(
            db,
            series.id,
            user_id,
            BlogCommentCreate(content="Reply to 1", parent_id=c1.id),
        )
        await create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Comment 2")
        )

        comments = await list_comments(db, series.id)
        assert len(comments) == 2  # 2 roots
        c1_found = next(c for c in comments if c.id == c1.id)
        assert len(c1_found.replies) == 1
        assert c1_found.replies[0].content == "Reply to 1"

    async def should_reject_comment_nonexistent_series(self, db: AsyncSession) -> None:
        with pytest.raises(BizError) as exc:
            await create_comment(db, 999, 1, BlogCommentCreate(content="Bad"))
        assert exc.value.errcode == BlogErr.SERIES_NOT_FOUND

    async def should_reject_reply_to_nonexistent_parent(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        with pytest.raises(BizError) as exc:
            await create_comment(
                db,
                series.id,
                user_id,
                BlogCommentCreate(content="Bad reply", parent_id=999),
            )
        assert exc.value.errcode == CommonErr.INVALID_INPUT

    async def should_reject_reply_parent_in_different_series(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        s1 = await _series(db, user_id=user_id, repo_name="blog-1")
        s2 = await _series(db, user_id=user_id, repo_name="blog-2")

        c1 = await create_comment(
            db, s1.id, user_id, BlogCommentCreate(content="S1 comment")
        )

        with pytest.raises(BizError) as exc:
            await create_comment(
                db,
                s2.id,
                user_id,
                BlogCommentCreate(content="Reply from S2", parent_id=c1.id),
            )
        assert exc.value.errcode == CommonErr.INVALID_INPUT

    async def should_delete_comment(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)
        comment = await create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Delete me")
        )

        await delete_comment(db, series.id, comment.id, user_id)
        assert await list_comments(db, series.id) == []

    async def should_cascade_delete_replies(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)
        c1 = await create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Root")
        )
        await create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Reply", parent_id=c1.id)
        )

        await delete_comment(db, series.id, c1.id, user_id)
        assert await list_comments(db, series.id) == []

    async def should_reject_delete_comment_wrong_user(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        other = await _user(db, username="bob", email="bob@bob.com")
        series = await _series(db, user_id=user_id)
        comment = await create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Mine")
        )

        with pytest.raises(BizError) as exc:
            await delete_comment(db, series.id, comment.id, other)
        assert exc.value.errcode == CommonErr.FORBIDDEN

    async def should_reject_delete_nonexistent_comment(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)

        with pytest.raises(BizError) as exc:
            await delete_comment(db, series.id, 999, user_id)
        assert exc.value.errcode == BlogErr.COMMENT_NOT_FOUND

    async def should_show_comment_with_profile(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        await update_profile(db, user_id, ProfileUpdate(nickname="Alice"))
        series = await _series(db, user_id=user_id)

        comment = await create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Hello")
        )
        assert comment.profile is not None
        assert comment.profile.nickname == "Alice"
        assert comment.profile.role == "member"


# ---- files ----


class TestBlogFiles:
    async def should_read_file_from_git(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)
        _seed_bare_repo(blog_dir, "my-blog", {"README.md": "# Hello World\n"})

        result = await get_file_content(db, series.id, "README.md")
        assert result["filepath"] == "README.md"
        assert result["content"] == "# Hello World\n"

    async def should_reject_file_nonexistent_series(self, db: AsyncSession) -> None:
        with pytest.raises(BizError) as exc:
            await get_file_content(db, 999, "README.md")
        assert exc.value.errcode == BlogErr.SERIES_NOT_FOUND

    async def should_reject_path_traversal(
        self, db: AsyncSession, blog_dir: str
    ) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)
        _seed_bare_repo(blog_dir, "my-blog", {"README.md": "# Hi"})

        with pytest.raises(BizError) as exc:
            await get_file_content(db, series.id, "../etc/passwd")
        assert exc.value.errcode == CommonErr.INVALID_INPUT

    async def should_read_nested_file(self, db: AsyncSession, blog_dir: str) -> None:
        user_id = await _user(db)
        series = await _series(db, user_id=user_id)
        _seed_bare_repo(
            blog_dir,
            "my-blog",
            {"posts/2026-07-23-hello.md": "# My Post\n"},
        )

        result = await get_file_content(db, series.id, "posts/2026-07-23-hello.md")
        assert "# My Post" in result["content"]


# ---- API routes ----


class TestBlogRoutes:
    async def _setup_user(self, db: AsyncSession) -> tuple[int, str]:
        """Create a user and return (user_id, bearer_token)."""
        user_id = await _user(db, username="testuser", email="test@example.com")
        token = create_access_token(
            user_id=user_id, account_level="normal", role="member"
        )
        return user_id, token

    def _auth_header(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def should_create_series_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        resp = await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={
                "title": "API Blog",
                "description": "Created via API",
                "repo_name": "api-blog",
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == 1
        assert data["repo_name"] == "api-blog"
        assert await asyncio.to_thread(
            os.path.isdir, os.path.join(blog_dir, "api-blog.git")
        )

    async def should_reject_create_without_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/blog/series",
            json={"title": "X", "repo_name": "x"},
        )
        assert resp.status_code == 403

    async def should_list_series_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        resp = await client.get("/api/v1/blog/series")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 1
        assert resp.json()["data"]["items"][0]["star_count"] == 0
        assert not resp.json()["data"]["items"][0]["is_starred"]

    async def should_list_series_with_star_as_authenticated(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )
        await client.post(
            "/api/v1/blog/series/1/star", headers=self._auth_header(token)
        )

        resp = await client.get("/api/v1/blog/series", headers=self._auth_header(token))
        item = resp.json()["data"]["items"][0]
        assert item["star_count"] == 1
        assert item["is_starred"]

    async def should_get_series_detail_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        resp = await client.get("/api/v1/blog/series/1")
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "A"
        assert resp.json()["data"]["file_tree"] is None

    async def should_update_series_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        resp = await client.put(
            "/api/v1/blog/series/1",
            headers=self._auth_header(token),
            json={"title": "Updated"},
        )
        assert resp.json()["data"]["title"] == "Updated"

    async def should_reject_update_by_other_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        # create second user
        await _user(db, username="other", email="other@example.com")
        token2 = create_access_token(user_id=2, account_level="normal", role="member")

        resp = await client.put(
            "/api/v1/blog/series/1",
            headers=self._auth_header(token2),
            json={"title": "Stolen"},
        )
        assert resp.status_code == 403

    async def should_delete_series_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        resp = await client.delete(
            "/api/v1/blog/series/1", headers=self._auth_header(token)
        )
        assert resp.status_code == 200
        # verify gone
        resp = await client.get("/api/v1/blog/series/1")
        assert resp.json()["code"] == BlogErr.SERIES_NOT_FOUND

    async def should_star_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        resp = await client.post(
            "/api/v1/blog/series/1/star", headers=self._auth_header(token)
        )
        assert resp.json()["data"]["starred"]
        assert resp.json()["data"]["star_count"] == 1

        resp = await client.post(
            "/api/v1/blog/series/1/star", headers=self._auth_header(token)
        )
        assert not resp.json()["data"]["starred"]
        assert resp.json()["data"]["star_count"] == 0

    async def should_comment_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        resp = await client.post(
            "/api/v1/blog/series/1/comments",
            headers=self._auth_header(token),
            json={"content": "Great!"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["content"] == "Great!"

    async def should_list_comments_threaded_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )
        resp = await client.post(
            "/api/v1/blog/series/1/comments",
            headers=self._auth_header(token),
            json={"content": "Root"},
        )
        parent_id = resp.json()["data"]["id"]

        await client.post(
            "/api/v1/blog/series/1/comments",
            headers=self._auth_header(token),
            json={"content": "Child", "parent_id": parent_id},
        )

        resp = await client.get("/api/v1/blog/series/1/comments")
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert len(items[0]["replies"]) == 1
        assert items[0]["replies"][0]["content"] == "Child"

    async def should_delete_comment_via_api(
        self, client: AsyncClient, db: AsyncSession, blog_dir: str
    ) -> None:
        _, token = await self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )
        await client.post(
            "/api/v1/blog/series/1/comments",
            headers=self._auth_header(token),
            json={"content": "Delete me"},
        )

        resp = await client.delete(
            "/api/v1/blog/series/1/comments/1", headers=self._auth_header(token)
        )
        assert resp.status_code == 200

        resp = await client.get("/api/v1/blog/series/1/comments")
        assert resp.json()["data"]["items"] == []

    async def should_get_404_for_nonexistent_series(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/blog/series/999")
        assert resp.json()["code"] == BlogErr.SERIES_NOT_FOUND

    async def should_require_auth_for_star(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/blog/series/1/star")
        assert resp.status_code == 403


class TestBlogWriteFiles:
    """PUT /blog/series/{id}/files/{path} 写 Git 文件端点测试。"""

    async def _owner_token(self, db: AsyncSession, username: str, email: str) -> str:
        user_id = await _user(db, username=username, email=email)
        return create_access_token(
            user_id=user_id, account_level="normal", role="member"
        )

    async def _create_series(
        self, client: AsyncClient, token: str, repo_name: str
    ) -> int:
        unique_repo = f"{repo_name}_{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/api/v1/blog/series",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "Write Test", "repo_name": unique_repo},
        )
        assert resp.status_code == 200
        return resp.json()["data"]["id"]

    async def should_write_and_read_back_file(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        token = await self._owner_token(db, "writeowner", "write@example.com")
        sid = await self._create_series(client, token, "w_owner")
        _auth = {"Authorization": f"Bearer {token}"}

        put = await client.put(
            f"/api/v1/blog/series/{sid}/files/posts/a.mdx",
            headers=_auth,
            json={"content": "# 标题\n正文", "message": "save"},
        )
        assert put.status_code == 200

        got = await client.get(f"/api/v1/blog/series/{sid}/files/posts/a.mdx")
        assert got.status_code == 200
        assert got.json()["data"]["content"].strip() == "# 标题\n正文"

    async def should_reject_non_owner_write(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        owner_token = await self._owner_token(db, "ownera", "ownera@example.com")
        sid = await self._create_series(client, owner_token, "w_nonowner")

        other_token = await self._owner_token(db, "otherb", "otherb@example.com")
        resp = await client.put(
            f"/api/v1/blog/series/{sid}/files/posts/a.mdx",
            headers={"Authorization": f"Bearer {other_token}"},
            json={"content": "x"},
        )
        assert resp.status_code == 403

    async def should_require_auth_for_write(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        owner_token = await self._owner_token(db, "ownerc", "ownerc@example.com")
        sid = await self._create_series(client, owner_token, "w_noauth")

        resp = await client.put(
            f"/api/v1/blog/series/{sid}/files/posts/a.mdx", json={"content": "x"}
        )
        assert resp.status_code == 403


class TestBlogPublish:
    """POST /blog/series/{id}/publish 发布为文章端点测试。

    发布链路：造 owner → 建 series（repo 名带 uuid 唯一后缀，防跨运行撞残留仓库）
    → PUT 写带 frontmatter 的 MDX → POST publish → GET /articles/{slug} 读回。
    """

    MDX_TEMPLATE = """---
title: {title}
category: {category}
tags: {tags}
slug: {slug}
---
{body}"""

    async def _owner_token(self, db: AsyncSession, username: str, email: str) -> str:
        user_id = await _user(db, username=username, email=email)
        return create_access_token(
            user_id=user_id, account_level="normal", role="member"
        )

    async def _make_series(self, client: AsyncClient, token: str) -> int:
        """建一个 repo 名带 uuid 唯一后缀的系列，返回 id。"""
        repo = f"pub_{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/api/v1/blog/series",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "Publish Series", "repo_name": repo},
        )
        assert resp.status_code == 200
        return resp.json()["data"]["id"]

    async def _write_file(
        self, client: AsyncClient, token: str, sid: int, filepath: str, content: str
    ) -> None:
        resp = await client.put(
            f"/api/v1/blog/series/{sid}/files/{filepath}",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": content, "message": "save"},
        )
        assert resp.status_code == 200

    @staticmethod
    def _mdx(
        title: str = "Hello Pub",
        category: str = "engineering",
        tags: str = "['python', 'test']",
        slug: str = "hello-pub",
        body: str = "# Hello Pub\n正文内容",
    ) -> str:
        return TestBlogPublish.MDX_TEMPLATE.format(
            title=title, category=category, tags=tags, slug=slug, body=body
        )

    async def should_publish_and_read_back(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        token = await self._owner_token(db, "pubowner1", "pubowner1@example.com")
        auth = {"Authorization": f"Bearer {token}"}
        sid = await self._make_series(client, token)

        content = self._mdx(
            title="Hello Pub",
            category="engineering",
            tags="['python', 'test']",
            slug="hello-pub",
            body="# Hello Pub\n正文内容",
        )
        await self._write_file(client, token, sid, "posts/a.mdx", content)

        resp = await client.post(
            f"/api/v1/blog/series/{sid}/publish",
            headers=auth,
            json={"filepath": "posts/a.mdx"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["slug"] == "hello-pub"
        assert data["title"] == "Hello Pub"
        assert data["category_title"] == "engineering"
        assert data["tags"] == ["python", "test"]

        # 发布后可从 articles 详情读回
        got = await client.get(f"/api/v1/articles/{data['slug']}")
        assert got.status_code == 200
        gdata = got.json()["data"]
        assert gdata["title"] == "Hello Pub"
        assert gdata["content"] == content

    async def should_be_idempotent_re_publish_updates(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        token = await self._owner_token(db, "pubowner2", "pubowner2@example.com")
        auth = {"Authorization": f"Bearer {token}"}
        sid = await self._make_series(client, token)

        await self._write_file(
            client, token, sid, "posts/a.mdx", self._mdx(body="# First\nv1")
        )
        r1 = await client.post(
            f"/api/v1/blog/series/{sid}/publish",
            headers=auth,
            json={"filepath": "posts/a.mdx"},
        )
        assert r1.status_code == 200
        slug = r1.json()["data"]["slug"]

        # 改 series 文件内容再重发：读回新 content，且不重复建记录
        new_content = self._mdx(body="# Second\nv2 更新")
        await self._write_file(client, token, sid, "posts/a.mdx", new_content)
        r2 = await client.post(
            f"/api/v1/blog/series/{sid}/publish",
            headers=auth,
            json={"filepath": "posts/a.mdx"},
        )
        assert r2.status_code == 200
        assert r2.json()["data"]["slug"] == slug

        got = await client.get(f"/api/v1/articles/{slug}")
        assert got.status_code == 200
        gdata = got.json()["data"]
        assert gdata["content"] == new_content

        # 同一 slug 仍是唯一记录（列表里只有一条）
        page = await client.get("/api/v1/articles")
        items = page.json()["data"]["items"]
        same_slug = [i for i in items if i["slug"] == slug]
        assert len(same_slug) == 1

    async def should_apply_override(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        token = await self._owner_token(db, "pubowner3", "pubowner3@example.com")
        auth = {"Authorization": f"Bearer {token}"}
        sid = await self._make_series(client, token)

        # frontmatter 元数据，被 override 覆盖
        await self._write_file(
            client, token, sid, "posts/a.mdx", self._mdx(slug="from-fm", body="# x")
        )

        resp = await client.post(
            f"/api/v1/blog/series/{sid}/publish",
            headers=auth,
            json={
                "filepath": "posts/a.mdx",
                "override": {
                    "slug": "from-override",
                    "category": "life",
                    "tags": ["override-tag"],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["slug"] == "from-override"
        assert data["category_title"] == "life"
        assert data["tags"] == ["override-tag"]

    async def should_reject_publish_by_non_owner(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        owner_token = await self._owner_token(db, "pubowner4", "pubowner4@example.com")
        sid = await self._make_series(client, owner_token)
        await self._write_file(
            client, owner_token, sid, "posts/a.mdx", self._mdx(body="# x")
        )

        other_token = await self._owner_token(db, "pubother4", "pubother4@example.com")
        resp = await client.post(
            f"/api/v1/blog/series/{sid}/publish",
            headers={"Authorization": f"Bearer {other_token}"},
            json={"filepath": "posts/a.mdx"},
        )
        assert resp.status_code == 403

    async def should_require_auth_for_publish(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        token = await self._owner_token(db, "pubowner5", "pubowner5@example.com")
        sid = await self._make_series(client, token)

        resp = await client.post(
            f"/api/v1/blog/series/{sid}/publish", json={"filepath": "posts/a.mdx"}
        )
        assert resp.status_code == 403
