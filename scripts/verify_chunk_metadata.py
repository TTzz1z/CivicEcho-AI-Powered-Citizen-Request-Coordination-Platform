"""Verify chunk metadata migration: create a new doc and inspect chunk metadata."""
from __future__ import annotations

import json
import os
import time
import urllib.request

BASE = "http://localhost:8000/api/v1"
SEED_PWD = os.environ.get("SEED_PASSWORD", "tingting-seed-demo-2026")


def req(method, path, *, headers=None, body=None):
    r = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    # login admin
    tok = req("POST", "/auth/login", body={"username": "admin_local", "password": SEED_PWD})["data"]["access_token"]
    hdr = {"Authorization": f"Bearer {tok}"}

    # create + publish
    payload = {
        "title": "P0-D-Chunk-Metadata-ReVerify",
        "kb_type": "policy",
        "visibility": "PUBLIC",
        "raw_content": (
            "重新验证 chunk 元数据迁移。本文档应在 kb_chunks 表中记录 "
            "embedding_model=Qwen/Qwen3-VL-Embedding-8B、provider=silicon_flow、"
            "dimension=1024、fallback=none。关键词：路灯、报修、时限。"
        ),
        "department_id": 1,
        "tags": ["reverify"],
    }
    doc = req("POST", "/kb/documents", headers=hdr, body=payload)["data"]
    doc_id = doc["id"]
    print(f"created doc_id={doc_id}")
    req("POST", f"/kb/documents/{doc_id}/publish", headers=hdr, body={"comment": "reverify"})
    time.sleep(2)

    # list chunks
    chunks = req("GET", f"/kb/documents/{doc_id}/chunks?page=1&page_size=5", headers=hdr)["data"]["items"]
    print(f"chunks count: {len(chunks)}")
    all_ok = True
    for c in chunks:
        print(
            f"  chunk {c['id']}: model={c['embedding_model']} "
            f"provider={c['embedding_provider']} dim={c['embedding_dimension']} "
            f"fallback={c['embedding_fallback']}"
        )
        if not c["embedding_model"] or not c["embedding_provider"] or not c["embedding_dimension"]:
            all_ok = False

    print(f"\nResult: {'PASS' if all_ok and chunks else 'FAIL'}")


if __name__ == "__main__":
    main()
