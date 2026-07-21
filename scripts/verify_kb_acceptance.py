"""KB acceptance verification — tests all 6 P0 items via real HTTP calls.

Uses only Python stdlib (urllib.request + json) to avoid dependency issues.

Usage (inside backend container):
    python /tmp/verify_kb_acceptance.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

sys.path.insert(0, "/app")

BASE_URL = "http://localhost:8000/api/v1"
SERVICE_TOKEN = os.environ["SERVICE_API_TOKEN"]
SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "tingting-seed-demo-2026")
PHASE4_PASSWORD = "Phase4-Pytest-Only!"  # set by tests/test_phase4_collaboration.py


def _request(method: str, path: str, *, headers: dict | None = None,
             json_body: dict | None = None, form_data: dict | None = None,
             files: dict | None = None, timeout: int = 15) -> tuple[int, dict | str]:
    url = f"{BASE_URL}{path}"
    hdrs = dict(headers or {})
    body_bytes: bytes | None = None

    if json_body is not None:
        body_bytes = json.dumps(json_body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    elif files is not None or form_data is not None:
        boundary = "----p0kbverify Boundary12345"
        hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        parts: list[bytes] = []
        for k, v in (form_data or {}).items():
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
            parts.append(f"{v}\r\n".encode())
        for field_name, (filename, content, mime) in (files or {}).items():
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
            )
            parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
            parts.append(content if isinstance(content, bytes) else content.encode("utf-8"))
            parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body_bytes = b"".join(parts)

    req = urllib.request.Request(url, data=body_bytes, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _login(username: str, password: str) -> str:
    status, body = _request("POST", "/auth/login", json_body={"username": username, "password": password})
    if status != 200:
        raise RuntimeError(f"login {username} failed: {status} {body}")
    return body["data"]["access_token"]


def _headers(token: str | None = None, *, service: bool = False) -> dict[str, str]:
    if service:
        return {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _show(label: str, status: int, body: Any) -> dict:
    if isinstance(body, dict):
        print(f"  {label}: HTTP {status} body={json.dumps(body, ensure_ascii=False)[:400]}")
        return body
    print(f"  {label}: HTTP {status} body={str(body)[:400]}")
    return {"raw": body}


def main() -> None:
    print("=" * 80)
    print("KB Acceptance Verification (P0-D, P0-E, P0-F, P0-C)")
    print("=" * 80)

    # --- Login as different roles ---
    print("\n[Setup] Logging in as different roles...")
    admin_token = _login("admin_local", SEED_PASSWORD)
    # phase4_staff0 is in dept 1 (urban-management); phase4_staff1 is in dept 2 (transport).
    dept_token = _login("phase4_staff0_71f0ccbc", PHASE4_PASSWORD)        # dept_id=1
    dept_token_2 = _login("phase4_staff1_71f0ccbc", PHASE4_PASSWORD)      # dept_id=2 (different)
    citizen_token = _login("citizen_local", SEED_PASSWORD)
    agent_token = _login("agent_local", SEED_PASSWORD)
    print("  admin_token OK; dept_token OK; dept_token_2 OK; citizen_token OK; agent_token OK")

    # phase4_staff0 is in dept 1 (urban-management), phase4_staff1 is in dept 2 (transport).
    phase4_dept_id = 1   # urban-management (dept_token's dept)
    phase5_dept_id = 2   # transport (dept_token_2's dept — different from phase4_dept_id)
    print(f"  phase4_dept_id={phase4_dept_id} phase5_dept_id={phase5_dept_id}")

    # ============================================================================
    # 1. Admin can access KB document management endpoints
    # ============================================================================
    print("\n[1] Admin KB document management endpoints...")
    status, body = _request("GET", "/kb/documents?page=1&page_size=5", headers=_headers(admin_token))
    _show("GET /kb/documents (admin)", status, body)
    admin_can_list = status == 200

    payload = {
        "title": "P0-KB-验收-管理員上傳-v1",
        "kb_type": "policy",
        "visibility": "PUBLIC",
        "raw_content": "这是一份用于验收测试的文档 v1。关键词：路灯维修时限、办理流程。",
        "department_id": phase4_dept_id,
        "tags": ["验收", "v1"],
    }
    status, body = _request("POST", "/kb/documents", json_body=payload, headers=_headers(admin_token))
    _show("POST /kb/documents (admin create v1)", status, body)
    doc_v1_id = body.get("data", {}).get("id") if isinstance(body, dict) else None
    print(f"  → doc_v1_id={doc_v1_id}")

    if doc_v1_id:
        # Admin direct-publish from DRAFT (skip submit-review which would set REVIEWING).
        st, bd = _request("POST", f"/kb/documents/{doc_v1_id}/publish",
                          json_body={"comment": "admin direct publish"}, headers=_headers(admin_token))
        _show("POST /publish (admin direct-publish v1)", st, bd)

    print(f"  → Item 1 (admin entry): {'PASS' if admin_can_list and doc_v1_id else 'FAIL'}")

    # ============================================================================
    # 2. department_staff can only manage their own department's documents
    # ============================================================================
    print("\n[2] Department staff scoping...")
    payload = {
        "title": "P0-KB-部门越权-应为403",
        "kb_type": "policy",
        "visibility": "PUBLIC",
        "raw_content": "部门越权测试",
        "department_id": phase5_dept_id,
        "tags": ["越权测试"],
    }
    status, body = _request("POST", "/kb/documents", json_body=payload, headers=_headers(dept_token))
    _show("POST /kb/documents (dept_staff cross-dept, expect 403)", status, body)
    dept_cross_dept_blocked = status in (403, 401)

    payload = {
        "title": "P0-KB-部门INTERNAL-应为403",
        "kb_type": "policy",
        "visibility": "INTERNAL",
        "raw_content": "INTERNAL 可见性测试",
        "department_id": phase4_dept_id,
        "tags": ["INTERNAL测试"],
    }
    status, body = _request("POST", "/kb/documents", json_body=payload, headers=_headers(dept_token))
    _show("POST /kb/documents (dept_staff INTERNAL, expect 403)", status, body)
    dept_internal_blocked = status in (403, 401)

    payload = {
        "title": "P0-KB-本部门上传-v1",
        "kb_type": "policy",
        "visibility": "DEPARTMENT",
        "raw_content": "本部门文档 v1",
        "department_id": phase4_dept_id,
        "tags": ["本部门"],
    }
    status, body = _request("POST", "/kb/documents", json_body=payload, headers=_headers(dept_token))
    _show("POST /kb/documents (dept_staff own dept, expect 200)", status, body)
    dept_own_doc_id = body.get("data", {}).get("id") if isinstance(body, dict) else None
    dept_own_ok = status == 200 and dept_own_doc_id is not None
    print(f"  → dept_own_doc_id={dept_own_doc_id}")

    print(f"  → Item 2 (dept scoping): "
          f"{'PASS' if dept_cross_dept_blocked and dept_internal_blocked and dept_own_ok else 'FAIL'}")

    # ============================================================================
    # 3. Department list filter
    # ============================================================================
    print("\n[3] Department list filter...")
    status, body = _request("GET", "/kb/documents?page=1&page_size=100", headers=_headers(dept_token))
    items = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
    violations = []
    for it in items:
        vis = it.get("visibility")
        dept_id = it.get("department_id")
        if vis == "INTERNAL":
            violations.append(("INTERNAL visible", it.get("id"), it.get("title")))
        elif vis == "DEPARTMENT" and dept_id != phase4_dept_id:
            violations.append(("other dept DEPARTMENT visible", it.get("id"), it.get("title")))
    print(f"  → {len(items)} items returned; violations={violations[:5]}")
    print(f"  → Item 3 (dept filter): {'PASS' if not violations else 'FAIL'}")

    # ============================================================================
    # 4. v1 → v2 → v3 version chain
    # ============================================================================
    print("\n[4] Version chain v1→v2→v3...")
    doc_v2_id = None
    doc_v3_id = None
    chain_ok = False
    if not doc_v1_id:
        print("  → SKIP (no v1 doc created)")
    else:
        files = {"file": ("v2.txt", b"v2 content", "text/plain")}
        data = {"title": "P0-KB-验收-管理員上傳-v2", "kb_type": "policy",
                "visibility": "PUBLIC", "department_id": str(phase4_dept_id),
                "doc_id": str(doc_v1_id), "tags": "验收,v2"}
        status, body = _request("POST", "/kb/documents/upload", form_data=data, files=files,
                                 headers=_headers(admin_token))
        _show("POST /kb/documents/upload (v2)", status, body)
        doc_v2_id = body.get("data", {}).get("id") if isinstance(body, dict) else None

        if doc_v2_id:
            _request("POST", f"/kb/documents/{doc_v2_id}/publish",
                     json_body={"comment": "v2 publish"}, headers=_headers(admin_token))

            files = {"file": ("v3.txt", b"v3 content", "text/plain")}
            data = {"title": "P0-KB-验收-管理員上傳-v3", "kb_type": "policy",
                    "visibility": "PUBLIC", "department_id": str(phase4_dept_id),
                    "doc_id": str(doc_v2_id), "tags": "验收,v3"}
            status, body = _request("POST", "/kb/documents/upload", form_data=data, files=files,
                                     headers=_headers(admin_token))
            _show("POST /kb/documents/upload (v3)", status, body)
            doc_v3_id = body.get("data", {}).get("id") if isinstance(body, dict) else None

            if doc_v3_id:
                _request("POST", f"/kb/documents/{doc_v3_id}/publish",
                         json_body={"comment": "v3 publish"}, headers=_headers(admin_token))

                status, body = _request("GET", f"/kb/documents/{doc_v3_id}/versions",
                                        headers=_headers(admin_token))
                _show(f"GET /kb/documents/{doc_v3_id}/versions", status, body)
                versions = body.get("data", []) if isinstance(body, dict) else []
                print(f"  → versions returned: {len(versions)}")
                for v in versions:
                    print(f"    id={v.get('id')} version={v.get('version')} status={v.get('status')} title={v.get('title')}")
                chain_ok = len(versions) >= 3 and \
                           any(v.get("version") == 1 for v in versions) and \
                           any(v.get("version") == 2 for v in versions) and \
                           any(v.get("version") == 3 for v in versions)

    print(f"  → Item 4 (v1→v2→v3): {'PASS' if chain_ok else 'FAIL'}")

    # ============================================================================
    # 5. PUBLIC / DEPARTMENT / INTERNAL visibility isolation
    # ============================================================================
    print("\n[5] Visibility isolation by role...")
    payloads = [
        ("PUBLIC", "P0-KB-vis-PUBLIC"),
        ("DEPARTMENT", "P0-KB-vis-DEPARTMENT"),
        ("INTERNAL", "P0-KB-vis-INTERNAL"),
    ]
    created_ids = []
    for vis, title in payloads:
        payload = {
            "title": title, "kb_type": "policy", "visibility": vis,
            "raw_content": f"{vis} 可见性测试", "department_id": phase4_dept_id,
            "tags": ["可见性测试"],
        }
        status, body = _request("POST", "/kb/documents", json_body=payload,
                                 headers=_headers(admin_token))
        _show(f"POST /kb/documents (admin create {vis})", status, body)
        did = body.get("data", {}).get("id") if isinstance(body, dict) else None
        if did:
            created_ids.append((vis, did))
            st, bd = _request("POST", f"/kb/documents/{did}/publish",
                              json_body={"comment": f"{vis} publish"}, headers=_headers(admin_token))
            _show(f"POST /publish ({vis})", st, bd)

    # 5a. citizen should see only PUBLIC
    status, body = _request("GET", "/kb/documents?page=1&page_size=100", headers=_headers(citizen_token))
    items = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
    citizen_visibilities = {it.get("visibility") for it in items}
    print(f"  citizen sees visibilities: {citizen_visibilities} (expected: only PUBLIC)")
    citizen_ok = citizen_visibilities == {"PUBLIC"} or citizen_visibilities <= {"PUBLIC"}

    # 5b. agent should see only PUBLIC
    status, body = _request("GET", "/kb/documents?page=1&page_size=100", headers=_headers(agent_token))
    items = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
    agent_visibilities = {it.get("visibility") for it in items}
    print(f"  agent sees visibilities: {agent_visibilities} (expected: only PUBLIC)")
    agent_ok = agent_visibilities == {"PUBLIC"} or agent_visibilities <= {"PUBLIC"}

    # 5c. department_staff (phase4) should see PUBLIC + DEPARTMENT(phase4) only, no INTERNAL
    status, body = _request("GET", "/kb/documents?page=1&page_size=100", headers=_headers(dept_token))
    items = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
    dept_visibilities = set()
    dept_violations = []
    for it in items:
        vis = it.get("visibility")
        dept_id = it.get("department_id")
        dept_visibilities.add(vis)
        if vis == "INTERNAL":
            dept_violations.append(("INTERNAL visible", it.get("id")))
        elif vis == "DEPARTMENT" and dept_id != phase4_dept_id:
            dept_violations.append(("other dept DEPARTMENT visible", it.get("id")))
    print(f"  dept_staff sees visibilities: {dept_visibilities} (expected: PUBLIC + DEPARTMENT only)")
    print(f"  dept_staff violations: {dept_violations[:5]}")
    dept_vis_ok = not dept_violations

    # 5d. admin should see all three
    status, body = _request("GET", "/kb/documents?page=1&page_size=100", headers=_headers(admin_token))
    items = body.get("data", {}).get("items", []) if isinstance(body, dict) else []
    admin_visibilities = {it.get("visibility") for it in items}
    print(f"  admin sees visibilities: {admin_visibilities} (expected: PUBLIC + DEPARTMENT + INTERNAL)")
    admin_vis_ok = {"PUBLIC", "DEPARTMENT", "INTERNAL"}.issubset(admin_visibilities)

    print(f"  → Item 5 (visibility isolation): "
          f"{'PASS' if citizen_ok and agent_ok and dept_vis_ok and admin_vis_ok else 'FAIL'}"
          f" (citizen={citizen_ok}, agent={agent_ok}, dept={dept_vis_ok}, admin={admin_vis_ok})")

    # ============================================================================
    # 6. Service principal can only read published PUBLIC docs
    # ============================================================================
    print("\n[6] Service principal PUBLIC-only access...")
    status, body = _request("GET", "/kb/documents?page=1&page_size=100", headers=_headers(service=True))
    _show("GET /kb/documents (service principal)", status, body)
    items = body.get("data", {}).get("items", []) if status == 200 and isinstance(body, dict) else []
    svc_visibilities = {it.get("visibility") for it in items}
    svc_statuses = {it.get("status") for it in items}
    print(f"  service principal sees visibilities: {svc_visibilities} statuses: {svc_statuses}")
    svc_list_ok = (svc_visibilities == {"PUBLIC"} or svc_visibilities <= {"PUBLIC"}) and \
                  (svc_statuses == {"PUBLISHED"} or svc_statuses <= {"PUBLISHED"})

    svc_dept_blocked = False
    svc_internal_blocked = False
    svc_write_blocked = False
    if created_ids:
        dept_doc_id = next((did for vis, did in created_ids if vis == "DEPARTMENT"), None)
        if dept_doc_id:
            status, body = _request("GET", f"/kb/documents/{dept_doc_id}", headers=_headers(service=True))
            _show(f"GET /kb/documents/{dept_doc_id} (service principal DEPARTMENT, expect 403)", status, body)
            svc_dept_blocked = status in (401, 403)

        internal_doc_id = next((did for vis, did in created_ids if vis == "INTERNAL"), None)
        if internal_doc_id:
            status, body = _request("GET", f"/kb/documents/{internal_doc_id}", headers=_headers(service=True))
            _show(f"GET /kb/documents/{internal_doc_id} (service principal INTERNAL, expect 403)", status, body)
            svc_internal_blocked = status in (401, 403)

        files = {"file": ("svc.txt", b"svc", "text/plain")}
        data = {"title": "P0-KB-服务主体越权-应为401", "kb_type": "policy", "visibility": "PUBLIC"}
        status, body = _request("POST", "/kb/documents/upload", form_data=data, files=files,
                                 headers=_headers(service=True))
        _show("POST /kb/documents/upload (service principal, expect 401)", status, body)
        svc_write_blocked = status in (401, 403)

    print(f"  → Item 6 (service principal PUBLIC-only): "
          f"{'PASS' if svc_list_ok and svc_dept_blocked and svc_internal_blocked and svc_write_blocked else 'FAIL'}"
          f" (list={svc_list_ok}, dept_blocked={svc_dept_blocked}, "
          f"internal_blocked={svc_internal_blocked}, write_blocked={svc_write_blocked})")

    # ============================================================================
    # Summary
    # ============================================================================
    print("\n" + "=" * 80)
    print("Summary:")
    print("=" * 80)
    print(f"  1. Admin KB entry:                {'PASS' if admin_can_list and doc_v1_id else 'FAIL'}")
    print(f"  2. Dept scoping:                  {'PASS' if dept_cross_dept_blocked and dept_internal_blocked and dept_own_ok else 'FAIL'}")
    print(f"  3. Dept list filter:              {'PASS' if not violations else 'FAIL'}")
    print(f"  4. Version chain v1→v2→v3:        {'PASS' if chain_ok else 'FAIL'}")
    print(f"  5. Visibility isolation:          {'PASS' if citizen_ok and agent_ok and dept_vis_ok and admin_vis_ok else 'FAIL'}")
    print(f"  6. Service principal PUBLIC-only: {'PASS' if svc_list_ok and svc_dept_blocked and svc_internal_blocked and svc_write_blocked else 'FAIL'}")


if __name__ == "__main__":
    main()
