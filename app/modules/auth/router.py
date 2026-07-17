from fastapi import APIRouter

from app.modules.common import ModuleStatus

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status", response_model=ModuleStatus)
async def auth_status() -> ModuleStatus:
    return ModuleStatus(
        module="auth",
        responsibility="Handle registration, login, user profiles, and basic member/admin roles.",
        next_steps=[
            "Create database tables",
            "Add password hashing and token authentication",
            "Expose registration, login, and current-user APIs",
        ],
    )
