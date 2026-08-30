from app.core.err import (
    NS_BOARDS,
    NS_COLUMNS,
    NS_CONTENT,
    NS_QA,
    ErrCode,
    register,
)


class ContentErr(ErrCode):
    CONTENT_NOT_FOUND = NS_CONTENT.err(1)
    COMMENT_NOT_FOUND = NS_CONTENT.err(2)
    BOARD_NOT_FOUND = NS_CONTENT.err(3)
    COLUMN_NOT_FOUND = NS_CONTENT.err(4)
    UNSUPPORTED_TYPE = NS_CONTENT.err(5)
    SLUG_TAKEN = NS_CONTENT.err(6)


class BoardErr(ErrCode):
    BOARD_NOT_FOUND = NS_BOARDS.err(1)
    SLUG_CONFLICT = NS_BOARDS.err(2)
    APPLICATION_NOT_FOUND = NS_BOARDS.err(3)
    APPLICATION_ALREADY_REVIEWED = NS_BOARDS.err(4)
    NOT_BOARD_OWNER = NS_BOARDS.err(5)
    BOARD_BANNED = NS_BOARDS.err(6)
    BOARD_NOT_PUBLIC = NS_BOARDS.err(7)
    DAILY_POST_LIMIT_REACHED = NS_BOARDS.err(8)
    CERTIFICATION_REQUIRED = NS_BOARDS.err(9)
    ALREADY_BANNED = NS_BOARDS.err(10)


class ColumnErr(ErrCode):
    APPLICATION_NOT_FOUND = NS_COLUMNS.err(1)
    NOT_FOUND = NS_COLUMNS.err(2)
    POST_NOT_FOUND = NS_COLUMNS.err(3)
    APPLICATION_ALREADY_REVIEWED = NS_COLUMNS.err(4)


class QaErr(ErrCode):
    QUESTION_NOT_FOUND = NS_QA.err(1)
    ANSWER_NOT_FOUND = NS_QA.err(2)
    QUESTION_NOT_OPEN = NS_QA.err(3)
    NOT_ASKER = NS_QA.err(4)
    BOUNTY_EXHAUSTED = NS_QA.err(5)
    CERTIFICATION_REQUIRED = NS_QA.err(6)


register(
    {
        ContentErr.CONTENT_NOT_FOUND: (404, "Content not found"),
        ContentErr.COMMENT_NOT_FOUND: (404, "Content comment not found"),
        ContentErr.BOARD_NOT_FOUND: (404, "Board not found"),
        ContentErr.COLUMN_NOT_FOUND: (404, "Column not found"),
        ContentErr.UNSUPPORTED_TYPE: (400, "Unsupported content type"),
        ContentErr.SLUG_TAKEN: (409, "Slug already taken"),
        BoardErr.BOARD_NOT_FOUND: (404, "板块不存在"),
        BoardErr.SLUG_CONFLICT: (409, "板块标识已被使用"),
        BoardErr.APPLICATION_NOT_FOUND: (404, "申请记录不存在"),
        BoardErr.APPLICATION_ALREADY_REVIEWED: (409, "申请已审核"),
        BoardErr.NOT_BOARD_OWNER: (403, "仅板块负责人可操作"),
        BoardErr.BOARD_BANNED: (403, "你已被本板块禁言"),
        BoardErr.BOARD_NOT_PUBLIC: (403, "本板块仅认证成员可发言"),
        BoardErr.DAILY_POST_LIMIT_REACHED: (429, "本板块今日发言已达上限"),
        BoardErr.CERTIFICATION_REQUIRED: (403, "需通过初级通识考试才能在本板块发言"),
        BoardErr.ALREADY_BANNED: (409, "该用户已被禁言"),
        ColumnErr.APPLICATION_NOT_FOUND: (404, "Column application not found"),
        ColumnErr.NOT_FOUND: (404, "Column not found"),
        ColumnErr.POST_NOT_FOUND: (404, "Column post not found"),
        ColumnErr.APPLICATION_ALREADY_REVIEWED: (
            409,
            "Column application already reviewed",
        ),
        QaErr.QUESTION_NOT_FOUND: (404, "问题不存在"),
        QaErr.ANSWER_NOT_FOUND: (404, "回答不存在"),
        QaErr.QUESTION_NOT_OPEN: (409, "问题已关闭，不可操作"),
        QaErr.NOT_ASKER: (403, "仅提问者本人可操作"),
        QaErr.BOUNTY_EXHAUSTED: (409, "悬赏已派发完毕"),
        QaErr.CERTIFICATION_REQUIRED: (403, "需认证用户才可提问或回答"),
    }
)
