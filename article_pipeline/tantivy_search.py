"""Remote Tantivy index search — runs on kk-pc WSL, called via SSH from elementary."""
import json, sys
from tantivy import Index

INDEX_PATH = "/mnt/d/aa-tantivy-index/"

query = sys.argv[1] if len(sys.argv) > 1 else ""
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5

if not query.strip():
    print(json.dumps([]))
    sys.exit(0)

try:
    idx = Index.open(INDEX_PATH)
    searcher = idx.searcher()
    q = idx.parse_query(query)
    results = searcher.search(q, limit)

    output = []
    seen = set()
    for score, addr in results.hits:
        doc = searcher.doc(addr)
        item = {"_score": score}
        title = doc.get_first("title")
        if title:
            title_str = str(title)[:500]
            # Deduplicate by title
            if title_str in seen:
                continue
            seen.add(title_str)
            item["title"] = title_str
        for name in ["author", "description", "text", "body", "content"]:
            val = doc.get_first(name)
            if val:
                item[name] = str(val)[:500]
                break
        output.append(item)

    print(json.dumps(output, ensure_ascii=False))
except Exception as e:
    print(json.dumps([{"error": str(e)}]))
