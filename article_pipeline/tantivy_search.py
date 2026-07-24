"""Remote Tantivy index search — runs on kk-pc WSL, called via SSH from elementary.

Deployment note: the *deployed* copy lives at
``/mnt/c/Users/feibisi-BH-PC/tantivy_search.py`` on kk-pc (see
research._search_cocobook_ssh); this file is the source of truth and must be
copied over after changes — the two had already drifted.

Contract with the caller: stdout carries a JSON array and nothing else.
Diagnostics go to stderr and a failure yields ``[]`` plus a non-zero exit code,
so a broken index can never be mistaken for research material. (It used to
print ``[{"error": ...}]`` on stdout, which the caller happily tagged
``_source="aa"`` and fed into the research note.)
"""
import json
import sys

INDEX_PATH = "/mnt/d/aa-tantivy-index/"

# Tantivy BM25 scores below this are noise for our corpus; keeping them was how
# unrelated books entered the note with no relevance floor at all.
MIN_SCORE = 1.0


def _die(message: str) -> None:
    print("[]")
    print(f"tantivy_search: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    # kk-pc runs a Windows-hosted WSL where stdout defaults to a non-UTF-8
    # codepage; without this the caller gets undecodable bytes.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    query = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    except ValueError:
        limit = 5

    if not query.strip():
        print(json.dumps([]))
        return

    try:
        from tantivy import Index
    except ImportError as exc:
        _die(f"tantivy not importable: {exc}")

    try:
        idx = Index.open(INDEX_PATH)
        searcher = idx.searcher()
        q = idx.parse_query(query)
        results = searcher.search(q, limit)
    except Exception as exc:
        _die(f"index {INDEX_PATH} unavailable: {type(exc).__name__}: {exc}")

    output = []
    seen = set()
    for score, addr in results.hits:
        if score < MIN_SCORE:
            continue
        doc = searcher.doc(addr)
        item = {"_score": float(score), "_origin": f"tantivy:{INDEX_PATH}"}
        title = doc.get_first("title")
        if title:
            title_str = str(title)[:500]
            if title_str in seen:  # deduplicate by title
                continue
            seen.add(title_str)
            item["title"] = title_str
        for name in ["author", "description", "text", "body", "content"]:
            val = doc.get_first(name)
            if val:
                item[name] = str(val)[:500]
                break
        # A hit with neither title nor body is not citable material.
        if len(item) > 2:
            output.append(item)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
