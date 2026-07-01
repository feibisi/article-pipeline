#!/usr/bin/env python3
"""Rebuild LanceDB semantic index from annotations DB using bge-m3. Mode=create each time."""
import sqlite3, time, shutil, requests, lancedb, pyarrow as pa, numpy as np
from pathlib import Path

ANNOTATIONS_DB = Path("/mnt/shared-context/cocobook/cocobook-annotations.db")
INDEX_DIR = Path("~/docs/ai-context/cocobook-annotations.lance")
OLLAMA_URL = "http://10.211.55.2:11434"
MODEL = "bge-m3:latest"
BATCH_SIZE = 50


def get_embedding(text: str) -> list[float] | None:
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/embeddings",
            json={"model": MODEL, "prompt": text[:512]}, timeout=15)
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception:
        return None


def main():
    conn = sqlite3.connect(str(ANNOTATIONS_DB.expanduser()))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, book_title, author, claim_type, claim, context
        FROM annotations ORDER BY id
    """).fetchall()
    conn.close()
    print(f"Loaded {len(rows)} annotations")

    embeddings = []
    records = []
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i+BATCH_SIZE]
        for row in batch:
            text = f"{row['claim_type']}: {row['claim']}"
            ctx = (row['context'] or '')[:100]
            if ctx:
                text += f" [ctx: {ctx}]"
            emb = get_embedding(text)
            if emb:
                embeddings.append(emb)
                records.append({
                    "id": row["id"], "book_title": row["book_title"] or "",
                    "author": row["author"] or "", "claim_type": row["claim_type"],
                    "claim": row["claim"], "context": row["context"] or "",
                })
        if (i + BATCH_SIZE) % 1000 == 0:
            print(f"  Embedded {i + BATCH_SIZE}/{len(rows)}")
        time.sleep(0.3)

    print(f"Valid: {len(embeddings)}/{len(rows)}")

    # Clean rebuild each time
    idx_path = INDEX_DIR.expanduser()
    if idx_path.exists():
        shutil.rmtree(str(idx_path), ignore_errors=True)
    idx_path.mkdir(parents=True, exist_ok=True)

    emb_array = np.array(embeddings, dtype=np.float32)
    table_data = [dict(r, vector=emb_array[i]) for i, r in enumerate(records)]

    schema = pa.schema([
        pa.field("id", pa.int64()), pa.field("book_title", pa.string()),
        pa.field("author", pa.string()), pa.field("claim_type", pa.string()),
        pa.field("claim", pa.string()), pa.field("context", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 1024)),
    ])

    db = lancedb.connect(str(idx_path))
    table = db.create_table("annotations", table_data, schema=schema, mode="create")
    print(f"\nIndexed {table.count_rows()} vectors")

    # Verify search works
    print("\nTest: 'WordPress 安全插件'")
    emb = get_embedding("WordPress 安全插件")
    if emb:
        results = table.search(emb).limit(3).to_list()
        for r in results:
            print(f"  [{r['claim_type']}] {r['claim'][:80]}")
    print("\nDone.")


if __name__ == "__main__":
    main()
