from app.core.err import NS_ARTICLES, ErrCode, register


class ArticleErr(ErrCode):
    NOT_FOUND = NS_ARTICLES.err(1)


register(
    {
        ArticleErr.NOT_FOUND: (404, "Article not found"),
    }
)
