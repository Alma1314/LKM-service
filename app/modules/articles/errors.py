from app.core.err import NS_ARTICLES, ErrCode, register


class ArticleErr(ErrCode):
    NOT_FOUND = NS_ARTICLES.err(1)
    COMMENT_NOT_FOUND = NS_ARTICLES.err(2)
    COMMENT_PARENT_MISMATCH = NS_ARTICLES.err(3)
    SLUG_CONFLICT = NS_ARTICLES.err(21)
    CATEGORY_NOT_FOUND = NS_ARTICLES.err(22)
    INVALID_STATUS_TRANSITION = NS_ARTICLES.err(23)
    CANNOT_HARD_DELETE_PUBLISHED = NS_ARTICLES.err(24)


register(
    {
        ArticleErr.NOT_FOUND: (404, "Article not found"),
        ArticleErr.COMMENT_NOT_FOUND: (404, "Comment not found"),
        ArticleErr.COMMENT_PARENT_MISMATCH: (
            400,
            "Parent comment does not belong to this article",
        ),
        ArticleErr.SLUG_CONFLICT: (409, "文章标识已存在"),
        ArticleErr.CATEGORY_NOT_FOUND: (404, "分类不存在"),
        ArticleErr.INVALID_STATUS_TRANSITION: (409, "非法的状态变更"),
        ArticleErr.CANNOT_HARD_DELETE_PUBLISHED: (409, "已发布文章不可硬删除"),
    }
)
