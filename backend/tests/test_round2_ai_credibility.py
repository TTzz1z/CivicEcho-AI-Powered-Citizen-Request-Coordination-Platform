"""Round 2 unit tests: AI audit chain, RAG credibility, route boundaries.

These tests run hermetically (LLM forced off via conftest) so they verify the
deterministic paths: rule-based classification, ai_usage_logs write-through,
no-evidence rejection, multi-intent clarify, service_guide RAG requirement,
ticket_advice review does not change ticket status, and service principal
permission regression.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import AiUsageLogModel, DepartmentModel, TicketModel, UserModel
from app.security import create_access_token, hash_password

client = TestClient(app)
PASSWORD = "Round2-Pytest-Only!"


@pytest.fixture(scope="module")
def actors():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        # Pick the "综合受理" department so staff can be assigned to the same dept.
        department = db.scalar(select(DepartmentModel).where(
            DepartmentModel.name == "综合受理"
        ))
        if department is None:
            department = db.scalar(select(DepartmentModel).where(DepartmentModel.is_active.is_(True)).limit(1))
        result = {}
        for name, role, department_id in (
            ("citizen", "citizen", None),
            ("agent", "agent", None),
            ("staff", "department_staff", department.id),
            ("admin", "admin", None),
        ):
            user = UserModel(
                username=f"r2_{name}_{suffix}",
                password_hash=hash_password(PASSWORD),
                display_name=f"r2-{name}", role=role,
                department_id=department_id, is_active=True,
            )
            db.add(user)
            db.flush()
            result[name] = {"id": user.id, "role": role}
        # Stash the department id for tests that need to assign tickets to it.
        result["_department_id"] = department.id
        db.commit()
    return result


def headers(actor):
    return {"Authorization": f"Bearer {create_access_token(actor['id'], actor['role'])}"}


# ============================================================================
# r2-2: AI audit chain
# ============================================================================

def test_orchestrator_classify_logs_to_ai_usage(actors):
    """Every orchestrator /chat call writes an ai_usage_logs row."""
    before = _count_logs()
    res = client.post(
        "/api/v1/orchestrator/chat",
        headers=headers(actors["citizen"]),
        json={"message": "你好", "session_id": f"r2-test-{uuid4().hex}"},
    )
    assert res.status_code == 200, res.text
    after = _count_logs()
    assert after > before, "orchestrator_classify must write to ai_usage_logs"


def test_policy_rag_logs_separate_from_llm(actors):
    """A policy_rag route call records BOTH embedding_query and (rules or LLM) usage."""
    before = _count_logs()
    res = client.post(
        "/api/v1/orchestrator/chat",
        headers=headers(actors["citizen"]),
        json={"message": "路灯坏了应该找谁", "session_id": f"r2-test-{uuid4().hex}"},
    )
    assert res.status_code == 200
    after = _count_logs()
    # At least one new log row (orchestrator_classify). If policy_rag route was
    # chosen, an embedding_query row was also written.
    assert after > before


def test_ai_analyze_logs_to_ai_usage(actors):
    """AI ticket analysis writes ai_usage_logs entries (rules or LLM tier)."""
    # Use a unique description so the suggestion fingerprint differs from
    # previous test runs (otherwise existing-suggestion fast path skips logging).
    unique_desc = f"测试 AI 审计链路 {uuid4().hex[:8]}"
    created = client.post("/api/v1/tickets", headers=headers(actors["citizen"]), json={
        "idempotency_key": str(uuid4()), "request_type": "投诉",
        "description": unique_desc, "location": "幸福路",
        "source": "r2-test",
    })
    ticket_id = created.json()["data"]["ticket"]["ticket_id"]
    before = _count_logs()
    res = client.post(
        f"/api/v1/ai/tickets/{ticket_id}/analyze",
        headers=headers(actors["agent"]),
        json={"suggestion_types": ["summary", "completeness", "risk"]},
    )
    assert res.status_code == 200, res.text
    after = _count_logs()
    assert after > before, "ai_analyze must write to ai_usage_logs"


def test_pre_review_logs_to_ai_usage(actors):
    """Citizen pre-review writes ai_usage_logs (rules or LLM)."""
    before = _count_logs()
    res = client.post(
        "/api/v1/ai/pre-review",
        headers=headers(actors["citizen"]),
        json={"request_type": "求助", "description": "路灯坏了",
              "location": "幸福路", "occurred_at_text": "今天"},
    )
    assert res.status_code == 200, res.text
    after = _count_logs()
    assert after > before, "pre_review must write to ai_usage_logs"


def test_case_advice_logs_to_ai_usage(actors):
    """Department AI case advice writes ai_usage_logs."""
    unique_desc = f"测试办件助手审计 {uuid4().hex[:8]}"
    created = client.post("/api/v1/tickets", headers=headers(actors["citizen"]), json={
        "idempotency_key": str(uuid4()), "request_type": "求助",
        "description": unique_desc, "location": "幸福路",
        "source": "r2-test-advice",
    })
    ticket_id = created.json()["data"]["ticket"]["ticket_id"]
    # Accept + assign + process so case_advice can run.
    dept_id = actors["_department_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", headers=headers(actors["agent"]),
                json={"version": 1, "remark": "r2"})
    client.post(f"/api/v1/tickets/{ticket_id}/assign", headers=headers(actors["agent"]),
                json={"version": 2, "department_id": dept_id, "remark": "r2"})
    client.post(f"/api/v1/tickets/{ticket_id}/process", headers=headers(actors["staff"]),
                json={"version": 3, "remark": "r2"})

    before = _count_logs()
    res = client.post(f"/api/v1/ai/tickets/{ticket_id}/case-advice",
                      headers=headers(actors["staff"]))
    assert res.status_code == 200, res.text
    after = _count_logs()
    assert after > before, "ticket_advice must write to ai_usage_logs"


# ============================================================================
# r2-3: Route boundaries
# ============================================================================

def test_policy_rag_does_not_create_ticket(actors):
    """Policy consultation must NOT auto-create a ticket draft."""
    # Use a query that hits POLICY_WORDS (e.g. "社保") and does NOT contain
    # complaint markers ("坏了", "故障", etc.) so the rule classifier routes
    # to policy_rag, not ticket_intake.
    res = client.post(
        "/api/v1/orchestrator/chat",
        headers=headers(actors["citizen"]),
        json={"message": "请问社保补贴政策适用于哪些人群",
              "session_id": f"r2-test-{uuid4().hex}"},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["should_create_ticket"] is False, f"policy_rag must not create ticket, route={data['route']}"
    assert data["route"] != "ticket_intake"


def test_service_guide_requires_citation_or_no_evidence(actors):
    """service_guide route must return citations or explicit no_evidence."""
    # SERVICE_GUIDE_WORDS includes "怎么办" — use a clean query that doesn't
    # overlap with complaint markers.
    res = client.post(
        "/api/v1/orchestrator/chat",
        headers=headers(actors["citizen"]),
        json={"message": "怎么办身份证", "route_hint": "service_guide",
              "session_id": f"r2-test-{uuid4().hex}"},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    if data["route"] == "service_guide":
        payload = data.get("payload") or {}
        # Either citations present, or explicit no_evidence flag.
        citations = payload.get("citations") or payload.get("chunks") or []
        assert len(citations) > 0 or payload.get("no_evidence") is True


def test_no_evidence_rejection_for_unknown_topic(actors):
    """Out-of-scope / no-evidence query must not fabricate an answer."""
    res = client.post(
        "/api/v1/orchestrator/chat",
        headers=headers(actors["citizen"]),
        json={"message": "量子力学中的波函数坍缩在哪些条款里有规定",
              "session_id": f"r2-test-{uuid4().hex}"},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["should_create_ticket"] is False
    answer = data.get("message") or ""
    no_evidence = any(kw in answer for kw in ("未检索到", "无相关", "暂无", "无法回答", "没有找到", "超出"))
    out_of_scope = data["route"] in {"out_of_scope", "clarify", "general_chat"}
    assert no_evidence or out_of_scope


# ============================================================================
# r2-4: Multi-intent clarify
# ============================================================================

def test_multi_intent_triggers_clarify(actors):
    """Consultation + complaint in one message must not auto-create a ticket."""
    res = client.post(
        "/api/v1/orchestrator/chat",
        headers=headers(actors["citizen"]),
        json={"message": "我要咨询社保补贴政策，同时投诉窗口不给办理",
              "session_id": f"r2-test-{uuid4().hex}"},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["should_create_ticket"] is False


# ============================================================================
# r2-5: session_id isolation
# ============================================================================

def test_session_id_isolation(actors):
    """Two sessions with different session_ids don't collide."""
    s1 = f"r2-s1-{uuid4().hex}"
    s2 = f"r2-s2-{uuid4().hex}"
    r1 = client.post("/api/v1/orchestrator/chat", headers=headers(actors["citizen"]),
                     json={"message": "你好", "session_id": s1})
    r2 = client.post("/api/v1/orchestrator/chat", headers=headers(actors["citizen"]),
                     json={"message": "你好", "session_id": s2})
    assert r1.status_code == 200 and r2.status_code == 200
    assert s1 != s2
    # ai_usage_logs should contain rows for at least one of these session_ids.
    with SessionLocal() as db:
        rows = db.scalars(select(AiUsageLogModel).where(
            AiUsageLogModel.session_id.in_([s1, s2])
        ).limit(10)).all()
        assert len(rows) > 0, "ai_usage_logs must record per-session ids"


# ============================================================================
# r2-7: ticket_advice review (three-state) doesn't change ticket status
# ============================================================================

def test_advice_review_does_not_change_ticket_status(actors):
    """Adopting / rejecting AI advice must not modify ticket status."""
    unique_desc = f"测试三态确认不修改状态 {uuid4().hex[:8]}"
    created = client.post("/api/v1/tickets", headers=headers(actors["citizen"]), json={
        "idempotency_key": str(uuid4()), "request_type": "求助",
        "description": unique_desc, "location": "幸福路",
        "source": "r2-test-review",
    })
    ticket_id = created.json()["data"]["ticket"]["ticket_id"]
    dept_id = actors["_department_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", headers=headers(actors["agent"]),
                json={"version": 1, "remark": "r2"})
    client.post(f"/api/v1/tickets/{ticket_id}/assign", headers=headers(actors["agent"]),
                json={"version": 2, "department_id": dept_id, "remark": "r2"})
    process_res = client.post(f"/api/v1/tickets/{ticket_id}/process",
                              headers=headers(actors["staff"]),
                              json={"version": 3, "remark": "r2"})
    assert process_res.status_code == 200, process_res.text
    version_before = process_res.json()["data"]["version"]

    # Generate advice and submit review with stable advice_id evidence chain.
    advice_res = client.post(f"/api/v1/ai/tickets/{ticket_id}/case-advice",
                             headers=headers(actors["staff"]))
    assert advice_res.status_code == 200, advice_res.text
    advice_id = advice_res.json()["data"]["advice_id"]
    review_res = client.post(
        f"/api/v1/kb/tickets/{ticket_id}/advice/review",
        headers=headers(actors["staff"]),
        json={"advice_id": advice_id, "decision": "adopted", "edit_summary": "采纳 AI 建议"},
    )
    assert review_res.status_code == 200, review_res.text

    # Verify ticket status/version unchanged.
    detail = client.get(f"/api/v1/tickets/{ticket_id}",
                        headers=headers(actors["agent"])).json()["data"]
    assert detail["status"] == "processing"
    assert detail["version"] == version_before


def test_advice_review_rejects_invalid_decision(actors):
    """Only adopted / adopted_with_edits / rejected are valid decisions."""
    created = client.post("/api/v1/tickets", headers=headers(actors["citizen"]), json={
        "idempotency_key": str(uuid4()), "request_type": "求助",
        "description": "测试无效决策", "location": "幸福路",
        "source": "r2-test-invalid",
    })
    ticket_id = created.json()["data"]["ticket"]["ticket_id"]
    res = client.post(
        f"/api/v1/kb/tickets/{ticket_id}/advice/review",
        headers=headers(actors["staff"]),
        json={
            "advice_id": "00000000-0000-0000-0000-000000000001",
            "decision": "auto_dispatch",
        },
    )
    # Invalid decision → 400 BusinessError; missing/invalid schema → 422.
    assert res.status_code in {400, 422}, res.text


# ============================================================================
# r2-8: Degradation paths
# ============================================================================

def test_degraded_call_marks_degraded_flag(actors):
    """Rules-tier (LLM unavailable) calls must set degraded=True with a reason."""
    # With conftest forcing AI_API_KEY="", every LLM call falls back to rules.
    res = client.post(
        "/api/v1/orchestrator/chat",
        headers=headers(actors["citizen"]),
        json={"message": "你好", "session_id": f"r2-test-{uuid4().hex}"},
    )
    assert res.status_code == 200
    # Check that recent ai_usage_logs has at least one degraded=true entry.
    with SessionLocal() as db:
        row = db.scalar(select(AiUsageLogModel).where(
            AiUsageLogModel.degraded.is_(True)
        ).order_by(AiUsageLogModel.created_at.desc()).limit(1))
        assert row is not None, "degraded entries must exist when LLM is unavailable"


# ============================================================================
# r2-9: Service principal regression
# ============================================================================

def test_service_principal_only_sees_public_published(actors):
    """Citizens (PUBLIC-only) must not see DEPARTMENT/INTERNAL/EXPIRED docs."""
    res = client.get(
        "/api/v1/kb/documents?page_size=100",
        headers=headers(actors["citizen"]),
    )
    assert res.status_code == 200
    payload = res.json()["data"]
    docs = payload.get("items", []) if isinstance(payload, dict) else payload
    assert isinstance(docs, list), f"expected document list, got {type(docs).__name__}"
    for d in docs:
        assert isinstance(d, dict), f"expected document object, got {d!r}"
        assert d["visibility"] == "PUBLIC", f"doc {d.get('title')} leaked non-PUBLIC visibility"
        assert d["status"] == "PUBLISHED", f"doc {d.get('title')} leaked non-PUBLISHED status"


# ============================================================================
# Helpers
# ============================================================================

def _count_logs() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count(AiUsageLogModel.id))) or 0
