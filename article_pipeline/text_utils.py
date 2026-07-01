"""Shared text post-processing utilities."""


def fix_em_dashes(article: str, max_dashes: int = 3) -> str:
    """Limit em-dashes (——) to max_dashes per article, replacing excess with periods."""
    dashes = article.count("——")
    if dashes <= max_dashes:
        return article
    parts = article.split("——")
    kept = parts[: max_dashes + 1]
    rest = "。".join(parts[max_dashes + 1 :])
    result = "——".join(kept)
    if rest:
        result += "。" + rest
    return result
