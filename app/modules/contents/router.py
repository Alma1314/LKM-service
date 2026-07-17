from fastapi import APIRouter

from app.modules.common import ModuleStatus

router = APIRouter(prefix="/contents", tags=["contents"])


@router.get("/status", response_model=ModuleStatus)
async def contents_status() -> ModuleStatus:
    return ModuleStatus(
        module="contents",
        responsibility="Support posts, notes, ideas, comments, likes, favorites, shares, and creator follows.",
        next_steps=[
            "Define post, comment, like, favorite, and follow models",
            "Add content publishing and editing APIs",
            "Add feed filtering by board, author, and tag",
        ],
    )
