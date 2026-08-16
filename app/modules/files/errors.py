from app.core.err import NS_FILES, ErrCode, register


class FileErr(ErrCode):
    NOT_FOUND = NS_FILES.err(1)
    STORE_ERROR = NS_FILES.err(2)
    TOO_LARGE = NS_FILES.err(3)
    INVALID_STATUS = NS_FILES.err(4)
    NOT_PENDING = NS_FILES.err(5)


register(
    {
        FileErr.NOT_FOUND: (404, "File not found"),
        FileErr.STORE_ERROR: (500, "File storage operation failed"),
        FileErr.TOO_LARGE: (413, "File exceeds upload size limit"),
        FileErr.INVALID_STATUS: (400, "Invalid file status transition"),
        FileErr.NOT_PENDING: (409, "File is not in pending status"),
    }
)
