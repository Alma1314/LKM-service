from app.core.err import NS_PROJECTS, ErrCode, register


class ProjectErr(ErrCode):
    PROJECT_NOT_FOUND = NS_PROJECTS.err(1)
    APPLICATION_NOT_FOUND = NS_PROJECTS.err(2)
    APPLICATION_ALREADY_REVIEWED = NS_PROJECTS.err(3)
    DUPLICATE_APPLICATION = NS_PROJECTS.err(4)
    MEMBER_USER_NOT_FOUND = NS_PROJECTS.err(5)


register(
    {
        ProjectErr.PROJECT_NOT_FOUND: (404, "项目不存在"),
        ProjectErr.APPLICATION_NOT_FOUND: (404, "孵化申请不存在"),
        ProjectErr.APPLICATION_ALREADY_REVIEWED: (409, "该申请已审核"),
        ProjectErr.DUPLICATE_APPLICATION: (409, "你对本项目已有待审申请"),
        ProjectErr.MEMBER_USER_NOT_FOUND: (404, "申请中的成员账号不存在"),
    }
)
