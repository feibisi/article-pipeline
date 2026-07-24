"""Shared text post-processing utilities."""


_CJK_CLOSING = "。！？；：，、）》」』】…"


def _join_with_period(left: str, right: str) -> str:
    """Join two fragments with a full stop, without doubling punctuation.

    The old implementation blindly inserted "。", so an em-dash that already sat
    next to punctuation produced "。。" / "，。" in the published article.
    """
    left_stripped = left.rstrip()
    if left_stripped and left_stripped[-1] in _CJK_CLOSING + ".!?":
        sep = ""
    else:
        sep = "。"
    return left_stripped + sep + right.lstrip()


def fix_em_dashes(article: str, max_dashes: int = 3) -> str:
    """Limit em-dashes (——) to max_dashes per article, replacing excess with periods."""
    dashes = article.count("——")
    if dashes <= max_dashes:
        return article
    parts = article.split("——")
    result = "——".join(parts[: max_dashes + 1])
    for extra in parts[max_dashes + 1:]:
        result = _join_with_period(result, extra)
    return result
