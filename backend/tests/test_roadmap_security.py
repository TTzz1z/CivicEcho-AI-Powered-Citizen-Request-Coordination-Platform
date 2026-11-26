from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_optional_principal
from app.authorization import AuthorizationPolicy, Principal
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.services.orchestrator_guard import OrchestratorGuard
from app.services.orchestrator_service import OrchestratorService


def test_ticket_scope_requires_owner_role_and_department():
    ticket = SimpleNamespace(
        creator_user_id=3, anonymous_creator_key=None, assigned_department_id=2,
        work_orders=[SimpleNamespace(department_id=4)], status="processing",
    )
    for principal, expected in [
        (Principal("anonymous"), False),
        (Principal("service"), False),
        (Principal("user", 3, role="citizen"), True),
        (Principal("user", 7, role="citizen"), False),
        (Principal("user", 8, role="department_staff", department_id=2), True),
        (Principal("user", 9, role="department_staff", department_id=4), True),
        (Principal("user", 10, role="department_staff", department_id=5), False),
        (Principal("user", 11, role="admin"), True),
    ]:
        assert AuthorizationPolicy.can_view(principal, ticket) is expected
    ticket.creator_user_id = None
    ticket.anonymous_creator_key = "owner-key"
    assert AuthorizationPolicy.can_view(Principal("service"), ticket, "owner-key")
    assert not AuthorizationPolicy.can_view(Principal("service"), ticket, "other-key")


def test_anonymous_ticket_lookup_does_not_use_client_context(monkeypatch):
    def reject_database_use():
        yield SimpleNamespace(scalar=lambda _: (_ for _ in ()).throw(AssertionError("unexpected query")))

    monkeypatch.setitem(app.dependency_overrides, get_db, reject_database_use)
    monkeypatch.setitem(app.dependency_overrides, get_optional_principal, lambda: Principal("anonymous"))
    response = TestClient(app).post("/api/v1/orchestrator/chat", json={
        "message": "查询工单进度 QT2026071300000001",
        "session_id": str(uuid4()),
        "session_context": {"role": "admin", "user_id": 1},
    })
    assert response.status_code == 200
    assert response.json()["data"]["rejection_reason"] == "ticket_access_denied"
    assert "当前状态" not in response.json()["data"]["message"]


def test_service_token_cannot_use_kb_or_orchestrator():
    headers = {"Authorization": f"Bearer {get_settings().service_api_token}"}
    client = TestClient(app)
    assert client.get("/api/v1/kb/documents", headers=headers).status_code == 403
    assert client.post("/api/v1/orchestrator/chat", headers=headers, json={"message": "你好"}).status_code == 403
    for path in ("/api/v1/tickets", "/api/v1/admin/ai-usage/stats", "/api/v1/admin/ai-usage/logs", "/api/v1/admin/ai-usage/budgets", "/api/v1/departments"):
        assert client.get(path, headers=headers).status_code == 403
    assert client.post("/api/v1/ai/pre-review", headers=headers, json={"description": "路灯损坏需要维修"}).status_code == 403


def test_service_ticket_detail_projects_only_status_fields(monkeypatch):
    from datetime import datetime, timezone
    from app.api.tickets import get_service

    record = SimpleNamespace(ticket_id="QT2026071300000001", request_type="咨询", status="pending",
                             status_label="待受理", created_at=datetime.now(timezone.utc), description="工单详情")
    service = SimpleNamespace(detail=lambda *args: record)
    monkeypatch.setitem(app.dependency_overrides, get_service, lambda: service)
    headers = {"Authorization": f"Bearer {get_settings().service_api_token}"}
    response = TestClient(app).get(f"/api/v1/tickets/{record.ticket_id}", headers=headers)
    assert response.status_code == 200
    assert set(response.json()["data"]) == {"ticket_id", "request_type", "status", "status_label", "created_at"}


def test_semantic_cache_isolated_by_principal_and_route(monkeypatch):
    guard = OrchestratorGuard()
    monkeypatch.setattr(guard, "_embed_for_cache", lambda *args, **kwargs: [1.0, 0.0])
    user = Principal("user", 1, role="department_staff", department_id=2)
    guard.cache_store(text="政策咨询", route="policy_rag", route_hint=None, payload={"message": "部门资料"}, principal=user)
    for principal in (
        Principal("anonymous"),
        Principal("user", 1, role="citizen"),
        Principal("user", 1, role="department_staff", department_id=3),
    ):
        assert guard._cache_lookup_semantic("政策咨询", None, principal=principal, route="policy_rag") is None
    assert guard._cache_lookup_semantic("政策咨询", None, principal=user, route="service_guide") is None
    assert guard._cache_lookup_semantic("政策咨询", None, principal=user, route="policy_rag")


def test_rag_answer_is_retrieved_again_after_content_changes(monkeypatch):
    service = OrchestratorService()
    monkeypatch.setattr(service.guard, "pre_check", lambda **kwargs: SimpleNamespace(allowed=True, degraded=False))
    monkeypatch.setattr(service.guard, "_cache_lookup_semantic", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("stale cache used")))
    monkeypatch.setattr(service.guard, "cache_store", lambda **kw: (_ for _ in ()).throw(AssertionError("RAG cached")))
    answers = iter(["旧政策", "新政策"])
    def execute(result, *args, **kwargs):
        result.message = next(answers)
        return result
    monkeypatch.setattr(service, "_execute_route", execute)
    context = {"user_id": 1, "role": "citizen"}
    principal = Principal("user", 1, role="citizen")
    first = service.process("政策咨询", context, principal=principal)
    second = service.process("政策咨询", context, principal=principal)
    assert (first.message, second.message) == ("旧政策", "新政策")
    assert not second.cache_hit


def test_model_caller_identity_reaches_sync_endpoint(monkeypatch):
    import app.api.dependencies as dependencies
    import app.api.orchestrator as orchestrator_api
    from app.model_governance import model_caller
    from app.services.orchestrator_service import OrchestratorResult

    monkeypatch.delitem(app.dependency_overrides, get_optional_principal, raising=False)
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: None)
    monkeypatch.setattr(dependencies, "_authenticate", lambda credentials, db: Principal("user", int(credentials.credentials), role="citizen"))
    seen = []
    def process(*args, **kwargs):
        seen.append(model_caller.get())
        return OrchestratorResult(primary_intent="greet", route="general_chat", confidence=1, message="你好")
    monkeypatch.setattr(orchestrator_api, "get_orchestrator", lambda: SimpleNamespace(process=process))
    client = TestClient(app)
    for token in ("7", "8"):
        assert client.post("/api/v1/orchestrator/chat", headers={"Authorization": f"Bearer {token}"}, json={"message": "你好"}).status_code == 200
    assert client.post("/api/v1/orchestrator/chat", json={"message": "你好"}).status_code == 200
    assert seen[:2] == ["user:7", "user:8"]
    assert seen[2].startswith("ip:")
