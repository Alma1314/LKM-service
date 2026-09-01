from app.core.err import NS_CONTENT, ErrCode, register


class ContentErr(ErrCode):
    CONTENT_NOT_FOUND = NS_CONTENT.err(1)
    COMMENT_NOT_FOUND = NS_CONTENT.err(2)
    BOARD_NOT_FOUND = NS_CONTENT.err(3)
    COLUMN_NOT_FOUND = NS_CONTENT.err(4)
    UNSUPPORTED_TYPE = NS_CONTENT.err(5)
    SLUG_TAKEN = NS_CONTENT.err(6)


register(
    {
        ContentErr.CONTENT_NOT_FOUND: (404, "Content not found"),
        ContentErr.COMMENT_NOT_FOUND: (404, "Content comment not found"),
        ContentErr.BOARD_NOT_FOUND: (404, "Board not found"),
        ContentErr.COLUMN_NOT_FOUND: (404, "Column not found"),
        ContentErr.UNSUPPORTED_TYPE: (400, "Unsupported content type"),
        ContentErr.SLUG_TAKEN: (409, "Slug already taken"),
    }
)
