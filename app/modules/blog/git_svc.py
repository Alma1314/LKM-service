import os
import shutil
import subprocess
import tempfile
from typing import Any

from app.core.config import settings
from app.core.err import BizError, CommonErr
from app.modules.blog.errors import BlogErr

# 文件树节点：值为嵌套子树，或哨兵字符串 "__BLOB__"（表示文件）。
TreeNode = dict[str, "TreeNode | str"]


def _repo_path(repo_name: str) -> str:
    base = os.path.abspath(settings.blog_repo_dir)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"{repo_name}.git")


def _run_git(repo_name: str, *args: str) -> str:
    path = _repo_path(repo_name)
    cmd = ["git", "--git-dir", path, *list(args)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            check=True,
        )
        return result.stdout.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        detail = e.stderr.decode("utf-8", errors="replace").strip() or str(e)
        raise BizError(BlogErr.GIT_ERROR, detail) from e
    except FileNotFoundError:
        raise BizError(BlogErr.GIT_ERROR, "git executable not found") from None


def init_bare_repo(repo_name: str) -> str:
    path = _repo_path(repo_name)
    if os.path.exists(path):
        raise BizError(BlogErr.GIT_ERROR, f"Repository '{repo_name}' already exists")
    try:
        subprocess.run(
            ["git", "init", "--bare", path],
            capture_output=True,
            timeout=10,
            check=True,
        )
        subprocess.run(
            ["git", "--git-dir", path, "config", "http.receivepack", "true"],
            capture_output=True,
            timeout=10,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        detail = e.stderr.decode("utf-8", errors="replace").strip() or str(e)
        raise BizError(BlogErr.GIT_ERROR, detail) from e
    return path


def delete_repo(repo_name: str) -> None:
    path = _repo_path(repo_name)
    if os.path.exists(path):
        shutil.rmtree(path)


def ensure_repo_has_commits(repo_name: str) -> bool:
    try:
        _run_git(repo_name, "rev-parse", "HEAD")
        return True
    except BizError:
        return False


def get_file_tree(repo_name: str) -> list[dict[str, Any]]:
    out = _run_git(repo_name, "ls-tree", "-r", "--name-only", "HEAD")
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        return []

    root: TreeNode = {}
    for line in lines:
        parts = line.split("/")
        cur: TreeNode = root
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                cur[part] = "__BLOB__"
            else:
                if part not in cur:
                    cur[part] = {}
                child = cur[part]
                if child == "__BLOB__":
                    cur[part] = {"__self__": "__BLOB__"}
                    child = cur[part]
                if isinstance(child, dict):
                    cur = child

    def _to_list(node: TreeNode | str) -> list[dict[str, Any]]:
        if not isinstance(node, dict):
            return []
        result: list[dict[str, Any]] = []
        for name, val in sorted(node.items()):
            if name == "__self__":
                continue
            if val == "__BLOB__":
                result.append({"name": name, "type": "blob"})
            else:
                result.append({"name": name, "type": "tree", "children": _to_list(val)})
        return result

    return _to_list(root)


def read_file(repo_name: str, filepath: str) -> str:
    filepath = filepath.lstrip("/")
    if ".." in filepath.split("/"):
        raise BizError(CommonErr.INVALID_INPUT, "Invalid file path")
    return _run_git(repo_name, "show", f"HEAD:{filepath}")


def get_readme(repo_name: str) -> str | None:
    try:
        return read_file(repo_name, "README.md")
    except BizError:
        return None


def _run_bare_check(repo_name: str, input_data: bytes | None, *args: str, env: dict[str, str] | None = None) -> str:
    """跑裸仓库 git 命令，失败时像 _run_git 一样抛出 BizError(GIT_ERROR)。"""
    path = _repo_path(repo_name)
    cmd = ["git", "--git-dir", path, *list(args)]
    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            timeout=30,
            check=True,
            env=env,
        )
        return result.stdout.decode("utf-8", errors="replace").strip()
    except subprocess.CalledProcessError as e:
        detail = e.stderr.decode("utf-8", errors="replace").strip() or str(e)
        raise BizError(BlogErr.GIT_ERROR, detail) from e
    except FileNotFoundError:
        raise BizError(BlogErr.GIT_ERROR, "git executable not found") from None


def write_file(
    repo_name: str,
    filepath: str,
    content: str,
    message: str = "update via editor",
    author: str = "LKM",
) -> None:
    """把 content 写入 series 仓库的 filepath 并提交（纯 bare 命令，无 worktree）。

    用临时 GIT_INDEX_FILE 做 add+commit，不触碰裸仓库真实 index。
    """
    filepath = filepath.lstrip("/")

    def _run(*args: str) -> str:
        return _run_git(repo_name, *args)

    with tempfile.TemporaryDirectory() as tmp:
        index_path = os.path.join(tmp, "index")
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = index_path
        # commit-tree 不接受 --author 参数，作者需通过环境变量传入
        env["GIT_AUTHOR_NAME"] = author
        env["GIT_AUTHOR_EMAIL"] = f"{author}@series.local"
        env["GIT_COMMITTER_NAME"] = author
        env["GIT_COMMITTER_EMAIL"] = f"{author}@series.local"

        # 写 blob
        blob = _run_bare_check(
            repo_name,
            content.encode("utf-8"),
            "hash-object", "-w", "--stdin",
            env=env,
        )

        # 更新临时 index
        _run_bare_check(
            repo_name, None,
            "update-index", "--add", "--cacheinfo", "100644", blob, filepath,
            env=env,
        )
        tree = _run_bare_check(repo_name, None, "write-tree", env=env)

        # 若已有 HEAD，作父提交；否则 root commit
        parent_args: list[str] = []
        try:
            parent = _run("rev-parse", "--verify", "HEAD").strip()
            if parent:
                parent_args = ["-p", parent]
        except BizError:
            pass

        commit = _run_bare_check(
            repo_name, None,
            "commit-tree", tree, *parent_args, "-m", message,
            env=env,
        )

        _run("update-ref", "refs/heads/master", commit)
