"""Role-split AI capabilities: triage_assistant vs handling_assistant."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.authorization import Principal
from app.errors import BusinessError, PermissionDenied
from app.services.ai_service import (
    CAP_HANDLING_ASSISTANT,
    CAP_TRIAGE_ASSISTANT,
    DEFAULT_INTAKE_NOTICE,
    AiService,
)


class _Ticket:
    def __init__(self, **kwargs):
        self.ticket_id = kwargs.get("ticket_id", "QT2026072200000001")
        self.status = kwargs.get("status", "pending")
        self.description = kwargs.get("description", "幸福路路灯坏了三天")
        self.location = kwargs.get("location", "幸福路88号")
        self.event = kwargs.get("event", "")
        self.occurred_at_text = kwargs.get("occurred_at_text", "3天")
        self.occurred_at_start = None
        self.contact = kwargs.get("contact", "")
        self.target = kwargs.get("target", "")
        self.request_type = kwargs.get("request_type", "投诉")
        self.priority = kwargs.get("priority", "normal")
        self.category_id = kwargs.get("category_id", 1)
        self.category = kwargs.get("category")
        self.assigned_department_id = kwargs.get("assigned_department_id", 7)
        self.department = kwargs.get("department")
        self.resolution_summary = kwargs.get("resolution_summary", "")
        self.resolution_measures = kwargs.get("resolution_measures", "")
        self.resolution_outcome = kwargs.get("resolution_outcome", "")
        self.public_reply = kwargs.get("public_reply", "")
        self.creator_user_id = kwargs.get("creator_user_id", 99)
        self.anonymous_creator_key = None
        self.work_orders = []


class _Dept:
    def __init__(self, id_, name):
        self.id = id_
        self.name = name


class _Cat:
    def __init__(self, name, default_department_id=7):
        self.name = name
        self.default_department_id = default_department_id


class _Repo:
    def __init__(self, ticket):
        self._ticket = ticket
        self.db = None
        self.added = []

    def ticket(self, ticket_id):
        return self._ticket if self._ticket.ticket_id == ticket_id else None

    def existing(self, *_args, **_kwargs):
        return None

    def add(self, item):
        if getattr(item, "created_at", None) is None:
            item.created_at = datetime.now(timezone.utc)
        self.added.append(item)
        return item

    def save(self, item):
        return item

    def get(self, suggestion_id):
        for item in self.added:
            if item.id == suggestion_id:
                return item
        return None

    def list_for_ticket(self, ticket_id):
        return [item for item in self.added if item.ticket_id == ticket_id]

    def active_departments(self):
        return [_Dept(7, "综合受理"), _Dept(1, "城市管理")]

    def assignment_history(self, *_args, **_kwargs):
        return []

    def candidates(self, *_args, **_kwargs):
        return []


class _Audit:
    def __init__(self):
        self.rows = []

    def log(self, *args, **kwargs):
        self.rows.append((args, kwargs))


class _Settings:
    ai_provider = "rules"
    ai_model_name = "rules"


def _principal(role, department_id=None, user_id=1):
    return Principal(kind="user", user_id=user_id, username=role, role=role, department_id=department_id)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    class _Llm:
        available = False

        def complete(self, *_args, **_kwargs):
            raise AssertionError("LLM should not be required in these unit tests")

    monkeypatch.setattr("app.services.ai_service.get_llm_client", lambda: _Llm())


def test_agent_triage_schema_and_no_finished_facts():
    ticket = _Ticket(status="pending", category=_Cat("路灯报修"))
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    rows = service.analyze(ticket.ticket_id, [CAP_TRIAGE_ASSISTANT], _principal("agent"), capability=CAP_TRIAGE_ASSISTANT)
    assert len(rows) == 1
    assert rows[0].suggestion_type == CAP_TRIAGE_ASSISTANT
    result = rows[0].result
    assert "department_candidates" in result
    assert "intake_notice_draft" in result
    assert "verification_checklist" not in result
    blob = json.dumps(result, ensure_ascii=False)
    for phrase in ("已经解决", "已经修复", "已完成维修"):
        assert phrase not in blob
    assert DEFAULT_INTAKE_NOTICE.split("，")[0] in result["intake_notice_draft"]


def test_department_handling_placeholder_without_facts():
    ticket = _Ticket(status="assigned", assigned_department_id=7, department=_Dept(7, "综合受理"), category=_Cat("路灯"))
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    rows = service.analyze(
        ticket.ticket_id, [CAP_HANDLING_ASSISTANT], _principal("department_staff", 7), capability=CAP_HANDLING_ASSISTANT,
    )
    result = rows[0].result
    assert rows[0].suggestion_type == CAP_HANDLING_ASSISTANT
    assert result["facts_sufficient"] is False
    assert "【位置】" in result["reply_draft"]
    assert result["verification_checklist"]
    assert result["handling_plan"]
    assert "已经修复" not in result["reply_draft"]


def test_citizen_cannot_call_triage_or_handling():
    ticket = _Ticket(status="pending")
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    with pytest.raises(PermissionDenied):
        service.analyze(ticket.ticket_id, [CAP_TRIAGE_ASSISTANT], _principal("citizen"), capability=CAP_TRIAGE_ASSISTANT)
    with pytest.raises(PermissionDenied):
        service.analyze(ticket.ticket_id, [CAP_HANDLING_ASSISTANT], _principal("citizen"), capability=CAP_HANDLING_ASSISTANT)


def test_other_department_cannot_call_handling():
    ticket = _Ticket(status="assigned", assigned_department_id=7, department=_Dept(7, "综合受理"))
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    with pytest.raises(PermissionDenied):
        service.analyze(
            ticket.ticket_id, [CAP_HANDLING_ASSISTANT], _principal("department_staff", 1), capability=CAP_HANDLING_ASSISTANT,
        )


def test_wrong_status_returns_409():
    ticket = _Ticket(status="resolved", assigned_department_id=7, department=_Dept(7, "综合受理"))
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    with pytest.raises(BusinessError) as exc:
        service.analyze(
            ticket.ticket_id, [CAP_HANDLING_ASSISTANT], _principal("department_staff", 7), capability=CAP_HANDLING_ASSISTANT,
        )
    assert exc.value.status_code == 409


def test_review_does_not_change_ticket_status_and_quality_vs_adopt():
    ticket = _Ticket(status="pending", category=_Cat("路灯"))
    repo = _Repo(ticket)
    audit = _Audit()
    service = AiService(repo, audit, _Settings())
    rows = service.analyze(ticket.ticket_id, [CAP_TRIAGE_ASSISTANT], _principal("agent"), capability=CAP_TRIAGE_ASSISTANT)
    suggestion_id = rows[0].id
    service.review(suggestion_id, "helpful", None, _principal("agent"))
    assert ticket.status == "pending"
    service.review(suggestion_id, "adopted", "ok", _principal("agent"))
    assert ticket.status == "pending"
    actions = [args[1] for args, _kwargs in audit.rows if len(args) > 1]
    assert "review_ai_suggestion_quality" in actions
    assert "review_ai_suggestion_adoption" in actions



def test_agent_cannot_request_document_draft():
    ticket = _Ticket(status="pending")
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    with pytest.raises(PermissionDenied):
        service.analyze(ticket.ticket_id, ["document_draft"], _principal("agent"))
