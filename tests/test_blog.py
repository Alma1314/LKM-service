import os
import subprocess

import pytest

from app.core.config import settings
from app.core.err import BizError, ErrCode
from app.modules.auth.schemas import ProfileUpdate
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.auth.service import update_profile
from app.modules.blog.models import BlogSeriesStatus
from app.modules.blog.schemas import (
    BlogCommentCreate,
    BlogSeriesCreate,
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
def blog_dir(monkeypatch, tmp_path):
    path = str(tmp_path / "blog_repos")
    monkeypatch.setattr(settings, "blog_repo_dir", path)
    yield path
    monkeypatch.setattr(settings, "blog_repo_dir", "blog_repos")


# ---- helpers ----


def _user(db, username="alice", email="alice@example.com"):
    from app.db.models import User, Profile
    user = User(
        username=username, email=email,
        hashed_password=hashpwd("secret123456"), account_level="normal",
    )
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id))
    db.flush()
    return user.id


def _series(db, user_id=1, repo_name="my-blog"):
    return create_series(
        db,
        user_id,
        BlogSeriesCreate(
            title="My Blog", description="A test blog series", repo_name=repo_name
        ),
    )


def _seed_bare_repo(repo_dir: str, repo_name: str, files: dict[str, str]):
    """Seed a bare git repo with files using git plumbing commands."""
    bare = os.path.join(repo_dir, f"{repo_name}.git")

    def _git(*args, stdin=b""):
        return subprocess.run(
            ["git", "--git-dir", bare] + list(args),
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
                rel = child_dir[len(prefix):]
                if "/" not in rel:
                    entries.append(f"040000 tree {child_tree}\t{rel}")
        tree_hash = (
            _git("mktree", stdin="\n".join(entries).encode()).stdout.decode().strip()
        )
        trees[d] = tree_hash

    root_tree = trees.get("", "")
    commit = (
        _git("commit-tree", root_tree, "-m", "initial commit")
        .stdout.decode()
        .strip()
    )
    _git("update-ref", "refs/heads/master", commit)


# ---- series CRUD ----


class TestBlogSeries:
    def should_create_series(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        assert series.id == 1
        assert series.owner_id == user_id
        assert series.title == "My Blog"
        assert series.status == BlogSeriesStatus.ACTIVE
        assert series.star_count == 0
        assert not series.is_starred
        # verify bare repo on disk
        assert os.path.isdir(os.path.join(blog_dir, "my-blog.git"))

    def should_reject_duplicate_repo_name(self, db, blog_dir):
        _user(db)
        _series(db, repo_name="taken")

        with pytest.raises(BizError) as exc:
            _series(db, repo_name="taken")

        assert exc.value.errcode == ErrCode.INVALID_INPUT

    def should_list_series(self, db, blog_dir):
        user_id = _user(db)
        _series(db, user_id=user_id, repo_name="blog-a")
        _series(db, user_id=user_id, repo_name="blog-b")

        items = list_series(db)
        assert len(items) == 2

    def should_list_series_with_star_info(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        toggle_star(db, series.id, user_id)
        items = list_series(db, current_user_id=user_id)
        assert items[0].star_count == 1
        assert items[0].is_starred

    def should_list_series_guest(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        toggle_star(db, series.id, user_id)
        items = list_series(db, current_user_id=None)
        assert items[0].star_count == 1
        assert not items[0].is_starred

    def should_get_series(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        detail = get_series(db, series.id)
        assert detail.id == series.id
        assert detail.file_tree is None  # empty repo

    def should_get_series_with_file_tree(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        _seed_bare_repo(
            blog_dir,
            "my-blog",
            {"README.md": "# Hello", "posts/2026-01-01.md": "# Post"},
        )

        detail = get_series(db, series.id)
        assert detail.file_tree is not None
        assert len(detail.file_tree) == 2  # README.md + posts/

    def should_reject_nonexistent_series(self, db):
        with pytest.raises(BizError) as exc:
            get_series(db, 999)

        assert exc.value.errcode == ErrCode.BLOG_SERIES_NOT_FOUND

    def should_update_series(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        updated = update_series(
            db,
            series.id,
            user_id,
            BlogSeriesUpdate(title="New Title", description="New desc"),
        )
        assert updated.title == "New Title"
        assert updated.description == "New desc"

    def should_reject_update_by_non_owner(self, db, blog_dir):
        user_id = _user(db)
        other = _user(db, username="bob", email="bob@bob.com")
        series = _series(db, user_id=user_id)

        with pytest.raises(BizError) as exc:
            update_series(db, series.id, other, BlogSeriesUpdate(title="Bad!"))

        assert exc.value.errcode == ErrCode.FORBIDDEN

    def should_delete_series(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        delete_series(db, series.id, user_id)

        with pytest.raises(BizError) as exc:
            get_series(db, series.id)
        assert exc.value.errcode == ErrCode.BLOG_SERIES_NOT_FOUND
        # repo physically removed
        assert not os.path.exists(os.path.join(blog_dir, "my-blog.git"))

    def should_reject_delete_by_non_owner(self, db, blog_dir):
        user_id = _user(db)
        other = _user(db, username="bob", email="bob@bob.com")
        series = _series(db, user_id=user_id)

        with pytest.raises(BizError) as exc:
            delete_series(db, series.id, other)

        assert exc.value.errcode == ErrCode.FORBIDDEN


# ---- stars ----


class TestBlogStars:
    def should_star_and_unstar(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        result = toggle_star(db, series.id, user_id)
        assert result.starred
        assert result.star_count == 1

        result = toggle_star(db, series.id, user_id)
        assert not result.starred
        assert result.star_count == 0

    def should_reject_star_nonexistent_series(self, db):
        with pytest.raises(BizError) as exc:
            toggle_star(db, 999, 1)
        assert exc.value.errcode == ErrCode.BLOG_SERIES_NOT_FOUND

    def should_count_stars_correctly(self, db, blog_dir):
        user_id = _user(db)
        other = _user(db, username="bob", email="bob@bob.com")
        series = _series(db, user_id=user_id)

        toggle_star(db, series.id, user_id)
        toggle_star(db, series.id, other)

        items = list_series(db)
        assert items[0].star_count == 2


# ---- comments ----


class TestBlogComments:
    def should_create_comment(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        comment = create_comment(db, series.id, user_id, BlogCommentCreate(content="Nice post!"))
        assert comment.id == 1
        assert comment.content == "Nice post!"
        assert comment.parent_id is None
        assert comment.replies == []

    def should_create_reply(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)
        parent = create_comment(db, series.id, user_id, BlogCommentCreate(content="Root"))

        reply = create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Reply", parent_id=parent.id)
        )
        assert reply.parent_id == parent.id

    def should_list_threaded_comments(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        c1 = create_comment(db, series.id, user_id, BlogCommentCreate(content="Comment 1"))
        create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Reply to 1", parent_id=c1.id)
        )
        create_comment(db, series.id, user_id, BlogCommentCreate(content="Comment 2"))

        comments = list_comments(db, series.id)
        assert len(comments) == 2  # 2 roots
        c1_found = next(c for c in comments if c.id == c1.id)
        assert len(c1_found.replies) == 1
        assert c1_found.replies[0].content == "Reply to 1"

    def should_reject_comment_nonexistent_series(self, db):
        with pytest.raises(BizError) as exc:
            create_comment(db, 999, 1, BlogCommentCreate(content="Bad"))
        assert exc.value.errcode == ErrCode.BLOG_SERIES_NOT_FOUND

    def should_reject_reply_to_nonexistent_parent(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        with pytest.raises(BizError) as exc:
            create_comment(
                db,
                series.id,
                user_id,
                BlogCommentCreate(content="Bad reply", parent_id=999),
            )
        assert exc.value.errcode == ErrCode.INVALID_INPUT

    def should_reject_reply_parent_in_different_series(self, db, blog_dir):
        user_id = _user(db)
        s1 = _series(db, user_id=user_id, repo_name="blog-1")
        s2 = _series(db, user_id=user_id, repo_name="blog-2")

        c1 = create_comment(db, s1.id, user_id, BlogCommentCreate(content="S1 comment"))

        with pytest.raises(BizError) as exc:
            create_comment(
                db,
                s2.id,
                user_id,
                BlogCommentCreate(content="Reply from S2", parent_id=c1.id),
            )
        assert exc.value.errcode == ErrCode.INVALID_INPUT

    def should_delete_comment(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)
        comment = create_comment(db, series.id, user_id, BlogCommentCreate(content="Delete me"))

        delete_comment(db, series.id, comment.id, user_id)
        assert list_comments(db, series.id) == []

    def should_cascade_delete_replies(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)
        c1 = create_comment(db, series.id, user_id, BlogCommentCreate(content="Root"))
        create_comment(
            db, series.id, user_id, BlogCommentCreate(content="Reply", parent_id=c1.id)
        )

        delete_comment(db, series.id, c1.id, user_id)
        assert list_comments(db, series.id) == []

    def should_reject_delete_comment_wrong_user(self, db, blog_dir):
        user_id = _user(db)
        other = _user(db, username="bob", email="bob@bob.com")
        series = _series(db, user_id=user_id)
        comment = create_comment(db, series.id, user_id, BlogCommentCreate(content="Mine"))

        with pytest.raises(BizError) as exc:
            delete_comment(db, series.id, comment.id, other)
        assert exc.value.errcode == ErrCode.FORBIDDEN

    def should_reject_delete_nonexistent_comment(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)

        with pytest.raises(BizError) as exc:
            delete_comment(db, series.id, 999, user_id)
        assert exc.value.errcode == ErrCode.BLOG_COMMENT_NOT_FOUND

    def should_show_comment_with_profile(self, db, blog_dir):
        user_id = _user(db)
        update_profile(db, user_id, ProfileUpdate(nickname="Alice"))
        series = _series(db, user_id=user_id)

        comment = create_comment(db, series.id, user_id, BlogCommentCreate(content="Hello"))
        assert comment.profile is not None
        assert comment.profile.nickname == "Alice"
        assert comment.profile.role == "member"


# ---- files ----


class TestBlogFiles:
    def should_read_file_from_git(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)
        _seed_bare_repo(blog_dir, "my-blog", {"README.md": "# Hello World\n"})

        result = get_file_content(db, series.id, "README.md")
        assert result["filepath"] == "README.md"
        assert result["content"] == "# Hello World\n"

    def should_reject_file_nonexistent_series(self, db):
        with pytest.raises(BizError) as exc:
            get_file_content(db, 999, "README.md")
        assert exc.value.errcode == ErrCode.BLOG_SERIES_NOT_FOUND

    def should_reject_path_traversal(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)
        _seed_bare_repo(blog_dir, "my-blog", {"README.md": "# Hi"})

        with pytest.raises(BizError) as exc:
            get_file_content(db, series.id, "../etc/passwd")
        assert exc.value.errcode == ErrCode.INVALID_INPUT

    def should_read_nested_file(self, db, blog_dir):
        user_id = _user(db)
        series = _series(db, user_id=user_id)
        _seed_bare_repo(
            blog_dir,
            "my-blog",
            {"posts/2026-07-23-hello.md": "# My Post\n"},
        )

        result = get_file_content(db, series.id, "posts/2026-07-23-hello.md")
        assert "# My Post" in result["content"]


# ---- API routes ----


class TestBlogRoutes:
    def _setup_user(self, db):
        """Create a user and return (user_id, bearer_token)."""
        user_id = _user(db, username="testuser", email="test@example.com")
        token = create_access_token(user_id=user_id, account_level="normal", role="member")
        return user_id, token

    def _auth_header(self, token: str):
        return {"Authorization": f"Bearer {token}"}

    async def should_create_series_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
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
        assert os.path.isdir(os.path.join(blog_dir, "api-blog.git"))

    async def should_reject_create_without_auth(self, client):
        resp = await client.post(
            "/api/v1/blog/series",
            json={"title": "X", "repo_name": "x"},
        )
        assert resp.status_code == 403

    async def should_list_series_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
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

    async def should_list_series_with_star_as_authenticated(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )
        await client.post("/api/v1/blog/series/1/star", headers=self._auth_header(token))

        resp = await client.get("/api/v1/blog/series", headers=self._auth_header(token))
        item = resp.json()["data"]["items"][0]
        assert item["star_count"] == 1
        assert item["is_starred"]

    async def should_get_series_detail_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        resp = await client.get("/api/v1/blog/series/1")
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "A"
        assert resp.json()["data"]["file_tree"] is None

    async def should_update_series_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
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

    async def should_reject_update_by_other_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        # create second user
        _user(db, username="other", email="other@example.com")
        token2 = create_access_token(user_id=2, account_level="normal", role="member")

        resp = await client.put(
            "/api/v1/blog/series/1",
            headers=self._auth_header(token2),
            json={"title": "Stolen"},
        )
        assert resp.status_code == 403

    async def should_delete_series_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        resp = await client.delete("/api/v1/blog/series/1", headers=self._auth_header(token))
        assert resp.status_code == 200
        # verify gone
        resp = await client.get("/api/v1/blog/series/1")
        assert resp.json()["code"] == 3001

    async def should_star_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
        await client.post(
            "/api/v1/blog/series",
            headers=self._auth_header(token),
            json={"title": "A", "repo_name": "a"},
        )

        resp = await client.post("/api/v1/blog/series/1/star", headers=self._auth_header(token))
        assert resp.json()["data"]["starred"]
        assert resp.json()["data"]["star_count"] == 1

        resp = await client.post("/api/v1/blog/series/1/star", headers=self._auth_header(token))
        assert not resp.json()["data"]["starred"]
        assert resp.json()["data"]["star_count"] == 0

    async def should_comment_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
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

    async def should_list_comments_threaded_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
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

    async def should_delete_comment_via_api(self, client, db, blog_dir):
        uid, token = self._setup_user(db)
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

    async def should_get_404_for_nonexistent_series(self, client):
        resp = await client.get("/api/v1/blog/series/999")
        assert resp.json()["code"] == 3001

    async def should_require_auth_for_star(self, client):
        resp = await client.post("/api/v1/blog/series/1/star")
        assert resp.status_code == 403
