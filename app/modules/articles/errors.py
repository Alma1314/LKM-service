from app.core.err import NS_ARTICLES, ErrCode, register


class ArticleErr(ErrCode):
    NOT_FOUND = NS_ARTICLES.err(1)
    COMMENT_NOT_FOUND = NS_ARTICLES.err(2)
    COMMENT_PARENT_MISMATCH = NS_ARTICLES.err(3)


register(
    {
        ArticleErr.NOT_FOUND: (404, "Article not found"),
        ArticleErr.COMMENT_NOT_FOUND: (404, "Comment not found"),
        ArticleErr.COMMENT_PARENT_MISMATCH: (
            400,
            "Parent comment does not belong to this article",
        ),
    }
)
