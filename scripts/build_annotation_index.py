#!/usr/bin/env python3
"""Build LanceDB semantic index for cocobook annotations using Mac Ollama bge-m3."""
import sqlite3
import json
import time
import requests
from pathlib import Path
import lancedb
import pyarrow as pa
import numpy as np

ANNOTATIONS_DB = Path("/mnt/shared-context/cocobook-annotations-stage.db")
INDEX_DIR = Path("/mnt/shared-context/annotations.lance")
OLLAMA_URL = "http://10.211.55.2:11434"
MODEL = "bge-m3:latest"
BATCH_SIZE = 20


def get_embedding(text: str) -> list[float] | None:
    """Get bge-m3 embedding for a single text."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": MODEL, "prompt": text[:512]},
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except (requests.RequestException, KeyError):
        return None


def main():
    # 1. Read annotations
    conn = sqlite3.connect(str(ANNOTATIONS_DB.expanduser()))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, book_title, author, claim_type, claim, context
        FROM annotations
        ORDER BY id
    """).fetchall()
    conn.close()
    print(f"Loaded {len(rows)} annotations")

    # 2. Generate embeddings in batches
    embeddings = []
    records = []
    for i, row in enumerate(rows):
        # Embed claim + first 100 chars of context for richer semantics
        text = f"{row['claim_type']}: {row['claim']}"
        ctx = (row['context'] or '')[:100]
        if ctx:
            text += f" [context: {ctx}]"

        emb = get_embedding(text)
        if emb:
            embeddings.append(emb)
            records.append({
                "id": row["id"],
                "book_title": row["book_title"] or "",
                "author": row["author"] or "",
                "claim_type": row["claim_type"],
                "claim": row["claim"],
                "context": row["context"] or "",
            })

        if (i + 1) % BATCH_SIZE == 0:
            print(f"  Embedded {i + 1}/{len(rows)}")
            time.sleep(0.3)  # don't hammer ollama

    print(f"Embedded {len(embeddings)}/{len(rows)} annotations")

    # 3. Build LanceDB
    INDEX_DIR.expanduser().mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(INDEX_DIR.expanduser()))

    # Prepare table data
    emb_array = np.array(embeddings, dtype=np.float32)
    table_data = []
    for i, rec in enumerate(records):
        table_data.append({
            "id": rec["id"],
            "book_title": rec["book_title"],
            "author": rec["author"],
            "claim_type": rec["claim_type"],
            "claim": rec["claim"],
            "context": rec["context"],
            "vector": emb_array[i],
        })

    schema = pa.schema([
        pa.field("id", pa.int64()),
        pa.field("book_title", pa.string()),
        pa.field("author", pa.string()),
        pa.field("claim_type", pa.string()),
        pa.field("claim", pa.string()),
        pa.field("context", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 1024)),
    ])

    table = db.create_table("annotations", table_data, schema=schema, mode="overwrite")
    print(f"Indexed {table.count_rows()} vectors in {INDEX_DIR}/annotations.lance")

    # 4. Test search
    query_emb = get_embedding("WordPress 安全漏洞防护")
    if query_emb:
        results = table.search(query_emb).limit(5).to_list()
        print(f"\nTest search 'WordPress 安全漏洞防护':")
        for r in results:
            print(f"  [{r['claim_type']} | {r['book_title'][:30]}] {r['claim'][:80]}")
    print("\nDone.")


if __name__ == "__main__":
    main()
