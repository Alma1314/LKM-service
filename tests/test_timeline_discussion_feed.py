from app.db.models import Board, ContentItem, ContentStatus, ContentType, User
from app.modules.timeline import feed as feed_src


async def _mk_user(db, username: str) -> User:
    u = User(username=username, email=f"{username}@x.test", hashed_password="x")
    db.add(u)
    await db.flush()
    return u


async def _mk_board(db, title: str) -> int:
    b = Board(title=title, slug=title, description="", status="active")
    db.add(b)
    await db.flush()
    return b.id


async def test_fetch_discussion_reads_content_items(db, client) -> None:
    author = await _mk_user(db, "feeduser")
    board_id = await _mk_board(db, "feedboard")
    item = ContentItem(
        content_type=ContentType.DISCUSSION,
        board_id=board_id,
        author_id=author.id,
        title="讨论帖",
        content="正文",
        status=ContentStatus.PUBLISHED,
        is_pinned=False,
    )
    db.add(item)
    await db.flush()

    rows = await feed_src.SOURCES["discussion"](
        db, None, None, None, 0, 20
    )
    assert rows, "应读出 content_items 里的 discussion"
    assert rows[0].item_type == "discussion"
    assert rows[0].url == f"/content/posts/{item.id}"
