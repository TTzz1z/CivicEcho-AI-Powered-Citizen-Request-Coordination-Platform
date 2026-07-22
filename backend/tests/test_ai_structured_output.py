"""Strict schema + RAG citation credibility tests for AI structured output.

Covers:
- invalid JSON / missing required fields / illegal enums
- cross-capability field leakage
- fabricated completion facts without real handling evidence
- answer citing non-existent [来源N]
- LLM failure / unavailable degrade field honesty
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ai_schemas import (
    build_conservative_rag_answer,
    extract_citation_indices,
    validate_handling_response,
    validate_rag_citations,
    validate_triage_response,
)
from app.authorization import Principal
from app.llm_client import LlmResult, LlmUsage
from app.services.ai_service import (
    CAP_HANDLING_ASSISTANT,
    CAP_TRIAGE_ASSISTANT,
    PLACEHOLDER_REPLY,
    AiService,
)
from app.services.kb_service import KnowledgeBaseService


# ---------------------------------------------------------------------------
# Shared fixtures / fakes
# ---------------------------------------------------------------------------

class _Ticket:
    def __init__(self, **kwargs):
        self.ticket_id = kwargs.get("ticket_id", "QT2026072200990001")
        self.status = kwargs.get("status", "pending")
        self.description = kwargs.get("description", "幸福路路灯坏了三天")
        self.location = kwargs.get("location", "幸福路88号")
        self.event = kwargs.get("event", "")
        self.occurred_at_text = kwargs.get("occurred_at_text", "3天")
        self.occurred_at_start = None
        self.contact = kwargs.get("contact", "13800000000")
        self.target = kwargs.get("target", "")
        self.request_type = kwargs.get("request_type", "投诉")
        self.priority = kwargs.get("priority", "normal")
        self.category_id = kwargs.get("category_id", 1)
        self.category = kwargs.get("category") or SimpleNamespace(name="路灯报修", default_department_id=7)
        self.assigned_department_id = kwargs.get("assigned_department_id", 7)
        self.department = kwargs.get("department") or SimpleNamespace(id=7, name="综合受理")
        self.resolution_summary = kwargs.get("resolution_summary", "")
        self.resolution_measures = kwargs.get("resolution_measures", "")
        self.resolution_outcome = kwargs.get("resolution_outcome", "")
        self.public_reply = kwargs.get("public_reply", "")
        self.creator_user_id = 1
        self.anonymous_creator_key = None
        self.work_orders = []


class _FakeDb:
    """No-op session so AiService commit/rollback after add(..., commit=False) succeeds."""

    def add(self, *_a, **_k):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def flush(self):
        pass

    def refresh(self, *_a, **_k):
        pass


class _Repo:
    def __init__(self, ticket):
        self._ticket = ticket
        self.db = _FakeDb()
        self.added = []

    def ticket(self, ticket_id):
        return self._ticket if self._ticket.ticket_id == ticket_id else None

    def existing(self, *_a, **_k):
        return None

    def add(self, item, *, commit: bool = True):
        del commit  # in-memory fake has no transactional boundary
        if getattr(item, "created_at", None) is None:
            item.created_at = datetime.now(timezone.utc)
        self.added.append(item)
        return item

    def save(self, item, *, commit: bool = True):
        del commit
        return item

    def get(self, suggestion_id):
        for item in self.added:
            if item.id == suggestion_id:
                return item
        return None

    def list_for_ticket(self, ticket_id):
        return [item for item in self.added if item.ticket_id == ticket_id]

    def active_departments(self):
        return [SimpleNamespace(id=7, name="综合受理"), SimpleNamespace(id=1, name="城市管理")]

    def assignment_history(self, *_a, **_k):
        return []

    def candidates(self, *_a, **_k):
        return []


class _Audit:
    def log(self, *args, **kwargs):
        pass


class _Settings:
    ai_provider = "rules"
    ai_model_name = "rules"


def _principal(role="agent", department_id=None):
    return Principal(kind="user", user_id=1, username=role, role=role, department_id=department_id)


def _valid_triage(**overrides):
    base = {
        "case_summary": {
            "description": "幸福路路灯损坏",
            "location": "幸福路",
            "duration": "3天",
            "affected_scope": "周边居民",
        },
        "classification": {
            "request_type": "投诉",
            "category": "路灯报修",
            "subcategory": "",
            "reason": "描述匹配市政照明",
        },
        "urgency": {"level": "normal", "emergency": False, "reason": "一般性诉求"},
        "completeness": {
            "complete": True,
            "known_fields": ["description", "location"],
            "missing_fields": [],
            "follow_up_questions": [],
            "completeness_score": 80,
        },
        "department_candidates": [
            {"department_name": "综合受理", "recommendation_level": "high", "reason": "默认"},
        ],
        "sla_recommendation": {
            "response_deadline": "24小时",
            "handling_deadline": "3个工作日",
            "reason": "内部参考",
        },
        "intake_notice_draft": "您的诉求已受理，平台将根据设施权属派发。",
        "advisory_only": True,
    }
    base.update(overrides)
    return base


def _valid_handling(**overrides):
    base = {
        "case_summary": {
            "description": "幸福路路灯损坏",
            "assigned_department": "综合受理",
            "classification": "路灯报修",
            "known_facts": [],
        },
        "verification_checklist": ["核实位置", "确认权属"],
        "handling_plan": ["现场核查", "实施处置"],
        "policy_references": ["市政照明维护规范"],
        "risk_warnings": ["临近 SLA"],
        "missing_handling_facts": ["核查结果"],
        "collaboration_suggestions": ["联系街道"],
        "evidence_checklist": ["现场照片"],
        "reply_template": PLACEHOLDER_REPLY,
        "reply_draft": PLACEHOLDER_REPLY,
        "facts_sufficient": False,
        "advisory_only": True,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema unit tests
# ---------------------------------------------------------------------------

def test_triage_rejects_missing_required_fields():
    payload = _valid_triage()
    del payload["case_summary"]
    result = validate_triage_response(payload)
    assert result.ok is False
    assert result.degrade_reason == "schema_validation_failed"


def test_triage_rejects_illegal_urgency_enum():
    payload = _valid_triage(urgency={"level": "super_urgent", "emergency": False, "reason": "x"})
    result = validate_triage_response(payload)
    assert result.ok is False
    assert result.degrade_reason == "schema_validation_failed"


def test_triage_rejects_handling_exclusive_fields():
    payload = _valid_triage(verification_checklist=["不应出现"], reply_draft="串用字段")
    result = validate_triage_response(payload)
    assert result.ok is False
    assert result.degrade_reason == "cross_capability_fields"


def test_handling_rejects_triage_exclusive_fields():
    payload = _valid_handling(intake_notice_draft="坐席告知语", department_candidates=[])
    result = validate_handling_response(payload, facts_sufficient=False)
    assert result.ok is False
    assert result.degrade_reason == "cross_capability_fields"


def test_handling_rejects_fabricated_completion_without_facts():
    payload = _valid_handling(
        reply_draft="经核查，该设施已经修复，已经处理完成。",
        facts_sufficient=False,
    )
    result = validate_handling_response(payload, facts_sufficient=False)
    assert result.ok is False
    assert result.degrade_reason == "fabricated_handling_facts"


def test_handling_accepts_placeholder_without_facts():
    result = validate_handling_response(_valid_handling(), facts_sufficient=False)
    assert result.ok is True
    assert result.data["facts_sufficient"] is False
    assert "【位置】" in result.data["reply_draft"]


def test_handling_accepts_real_facts_when_sufficient():
    payload = _valid_handling(
        reply_draft="已现场核查并完成维修，路灯已恢复正常。",
        facts_sufficient=True,
        missing_handling_facts=[],
        case_summary={
            "description": "路灯",
            "assigned_department": "综合受理",
            "classification": "路灯",
            "known_facts": ["已更换灯头"],
        },
    )
    result = validate_handling_response(payload, facts_sufficient=True)
    assert result.ok is True
    assert "已恢复正常" in result.data["reply_draft"]


def test_confidence_out_of_range_rejected():
    payload = _valid_triage(confidence=150)
    result = validate_triage_response(payload)
    assert result.ok is False
    assert result.degrade_reason == "schema_validation_failed"


# ---------------------------------------------------------------------------
# RAG citation post-validation
# ---------------------------------------------------------------------------

def test_citation_rejects_nonexistent_source_index():
    citations = [{"index": 1, "title": "政策A", "excerpt": "路灯维修由市政负责"}]
    result = validate_rag_citations("根据[来源1]和[来源9]，路灯应报修。", citations)
    assert result.ok is False
    assert result.degrade_reason == "citation_index_not_found"


def test_citation_rejects_missing_markers_when_evidence_exists():
    citations = [{"index": 1, "title": "政策A", "excerpt": "路灯维修由市政负责"}]
    result = validate_rag_citations("路灯坏了找市政即可。", citations)
    assert result.ok is False
    assert result.degrade_reason == "missing_citations"


def test_citation_accepts_valid_markers():
    citations = [
        {"index": 1, "title": "政策A", "excerpt": "路灯"},
        {"index": 2, "title": "政策B", "excerpt": "时限"},
    ]
    result = validate_rag_citations("结论见[来源1]，时限见[来源2]。", citations)
    assert result.ok is True
    assert extract_citation_indices(result.data["answer"]) == [1, 2]


def test_conservative_answer_only_uses_real_indices():
    citations = [{"index": 1, "title": "政策A", "excerpt": "原文片段"}]
    answer = build_conservative_rag_answer(citations, reason="citation_index_not_found")
    assert "[来源1]" in answer
    assert "[来源9]" not in answer
    assert validate_rag_citations(answer, citations).ok is True


def test_rag_answer_degrades_on_fake_citation(monkeypatch):
    """kb_service.rag_answer must not keep answers that cite missing sources."""
    svc = KnowledgeBaseService.__new__(KnowledgeBaseService)
    svc.db = SimpleNamespace()
    svc.settings = SimpleNamespace(kb_rag_top_k=5)

    citations = [{"index": 1, "title": "政策A", "excerpt": "路灯维修", "doc_id": 1}]
    chunks = [{
        "content": "路灯维修由市政负责",
        "document": {
            "id": 1, "title": "政策A", "doc_number": "A-1",
            "department_name": "市政", "published_at": "2026-01-01",
            "issuing_authority": "市政", "status": "PUBLISHED", "version": 1,
            "kb_type": "policy", "effective_at": None, "expires_at": None,
            "published_department_name": "市政",
        },
        "is_expired": False, "chunk_index": 0, "score": 0.9,
    }]

    monkeypatch.setattr(svc, "retrieve", lambda *a, **k: {
        "chunks": chunks, "accessible_doc_count": 1, "no_evidence": False,
    })
    monkeypatch.setattr(
        svc, "_generate_answer",
        lambda *a, **k: ("根据[来源99]可以认定已经修复。", True, LlmResult(
            success=True, data=None, model="mock-model", content="根据[来源99]可以认定已经修复。",
            usage=LlmUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )),
    )
    monkeypatch.setattr(
        "app.services.kb_service.get_llm_client",
        lambda: SimpleNamespace(provider="deepseek", model="mock-model", available=True),
    )

    class _Rec:
        def __init__(self, *_a, **_k):
            pass

        def record_rules_call(self, *args, **kwargs):
            pass

    monkeypatch.setattr("app.services.kb_service.AiUsageRecorder", _Rec)

    result = KnowledgeBaseService.rag_answer(svc, "路灯坏了找谁", _principal("citizen"))
    assert result["degraded"] is True
    assert result["degrade_reason"] == "citation_index_not_found"
    assert "[来源99]" not in result["answer"]
    assert "[来源1]" in result["answer"]
    assert result["citations"][0]["index"] == 1
    assert result["provider"] == "rules"
    assert result["usage_unavailable"] is True


def test_rag_answer_llm_unavailable_fields(monkeypatch):
    svc = KnowledgeBaseService.__new__(KnowledgeBaseService)
    svc.db = SimpleNamespace()
    chunks = [{
        "content": "路灯维修由市政负责",
        "document": {
            "id": 1, "title": "政策A", "doc_number": "A-1",
            "department_name": "市政", "published_at": "2026-01-01",
            "issuing_authority": "市政", "status": "PUBLISHED", "version": 1,
            "kb_type": "policy", "effective_at": None, "expires_at": None,
            "published_department_name": "市政",
        },
        "is_expired": False, "chunk_index": 0, "score": 0.9,
    }]
    monkeypatch.setattr(svc, "retrieve", lambda *a, **k: {
        "chunks": chunks, "accessible_doc_count": 1, "no_evidence": False,
    })
    monkeypatch.setattr(
        svc, "_generate_answer",
        lambda *a, **k: (
            build_conservative_rag_answer(
                [{"index": 1, "title": "政策A", "excerpt": "路灯维修由市政负责"}],
                reason="llm_unavailable",
            ),
            False,
            None,
        ),
    )
    monkeypatch.setattr(
        "app.services.kb_service.get_llm_client",
        lambda: SimpleNamespace(provider="deepseek", model="mock", available=False),
    )

    class _Rec:
        def __init__(self, *_a, **_k):
            pass

        def record_rules_call(self, *args, **kwargs):
            pass

    monkeypatch.setattr("app.services.kb_service.AiUsageRecorder", _Rec)

    result = KnowledgeBaseService.rag_answer(svc, "路灯坏了", _principal("citizen"))
    assert result["provider"] == "rules"
    assert result["model"] in {"rules-v2", "rules-citation-guard", "rules"}
    assert result["degraded"] is True
    assert result["degrade_reason"] in {"llm_unavailable", "missing_citations"}
    assert result["usage_unavailable"] is True
    assert result["citations"][0]["index"] == 1


# ---------------------------------------------------------------------------
# ai_service integration: illegal LLM payloads must degrade, not persist
# ---------------------------------------------------------------------------

class _FakeLlm:
    def __init__(self, result: LlmResult):
        self.available = True
        self.provider = "deepseek"
        self.model = "mock-model"
        self._result = result

    def complete(self, *_a, **_k):
        return self._result


@pytest.fixture
def _mute_usage(monkeypatch):
    class _Rec:
        def __init__(self, *_a, **_k):
            pass

        def record_llm_call(self, *args, **kwargs):
            pass

        def record_rules_call(self, *args, **kwargs):
            pass

    monkeypatch.setattr("app.services.ai_service.AiUsageRecorder", _Rec)


def test_analyze_invalid_json_degrades_and_does_not_persist_raw(monkeypatch, _mute_usage):
    ticket = _Ticket(status="pending")
    repo = _Repo(ticket)
    service = AiService(repo, _Audit(), _Settings())
    monkeypatch.setattr(
        "app.services.ai_service.get_llm_client",
        lambda: _FakeLlm(LlmResult(
            success=False, data=None, model="mock-model",
            error="json_decode_error", error_code="json_decode_error",
            usage=LlmUsage(unavailable=True),
        )),
    )
    rows = service.analyze(ticket.ticket_id, [CAP_TRIAGE_ASSISTANT], _principal("agent"),
                           capability=CAP_TRIAGE_ASSISTANT)
    assert len(rows) == 1
    result = rows[0].result
    assert result["degraded"] is True
    assert result["degrade_reason"] == "json_decode_error"
    assert result["provider"] == "rules"
    assert result["usage_unavailable"] is True
    assert "department_candidates" in result
    # Must be rules-shaped triage, not raw LLM garbage.
    assert "verification_checklist" not in result
    raw = json.loads(repo.added[0].result_json)
    assert raw.get("degraded") is True


def test_analyze_missing_required_field_degrades(monkeypatch, _mute_usage):
    ticket = _Ticket(status="pending")
    repo = _Repo(ticket)
    service = AiService(repo, _Audit(), _Settings())
    bad = _valid_triage()
    del bad["urgency"]
    monkeypatch.setattr(
        "app.services.ai_service.get_llm_client",
        lambda: _FakeLlm(LlmResult(
            success=True, data=bad, model="mock-model",
            usage=LlmUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )),
    )
    rows = service.analyze(ticket.ticket_id, [CAP_TRIAGE_ASSISTANT], _principal("agent"),
                           capability=CAP_TRIAGE_ASSISTANT)
    result = rows[0].result
    assert result["degraded"] is True
    assert result["degrade_reason"] == "schema_validation_failed"
    assert result["provider"] == "rules"
    assert "urgency" in result  # rules fallback restores required fields


def test_analyze_illegal_enum_degrades(monkeypatch, _mute_usage):
    ticket = _Ticket(status="pending")
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    bad = _valid_triage(urgency={"level": "critical", "emergency": True, "reason": "x"})
    monkeypatch.setattr(
        "app.services.ai_service.get_llm_client",
        lambda: _FakeLlm(LlmResult(success=True, data=bad, model="mock-model",
                                   usage=LlmUsage(unavailable=True))),
    )
    result = service.analyze(ticket.ticket_id, [CAP_TRIAGE_ASSISTANT], _principal("agent"),
                             capability=CAP_TRIAGE_ASSISTANT)[0].result
    assert result["degraded"] is True
    assert result["degrade_reason"] == "schema_validation_failed"
    assert result["urgency"]["level"] in {"normal", "expedited", "urgent", "major"}


def test_analyze_cross_capability_fields_degrade(monkeypatch, _mute_usage):
    ticket = _Ticket(status="pending")
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    bad = _valid_triage(verification_checklist=["串用"], reply_draft="不应出现")
    monkeypatch.setattr(
        "app.services.ai_service.get_llm_client",
        lambda: _FakeLlm(LlmResult(success=True, data=bad, model="mock-model",
                                   usage=LlmUsage(unavailable=True))),
    )
    result = service.analyze(ticket.ticket_id, [CAP_TRIAGE_ASSISTANT], _principal("agent"),
                             capability=CAP_TRIAGE_ASSISTANT)[0].result
    assert result["degraded"] is True
    assert result["degrade_reason"] == "cross_capability_fields"
    assert "verification_checklist" not in result


def test_analyze_fabricated_handling_facts_degrade(monkeypatch, _mute_usage):
    ticket = _Ticket(status="assigned", assigned_department_id=7)
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    bad = _valid_handling(reply_draft="设施已经修复，已经处理完成。")
    monkeypatch.setattr(
        "app.services.ai_service.get_llm_client",
        lambda: _FakeLlm(LlmResult(success=True, data=bad, model="mock-model",
                                   usage=LlmUsage(unavailable=True))),
    )
    result = service.analyze(
        ticket.ticket_id, [CAP_HANDLING_ASSISTANT],
        _principal("department_staff", 7), capability=CAP_HANDLING_ASSISTANT,
    )[0].result
    assert result["degraded"] is True
    assert result["degrade_reason"] == "fabricated_handling_facts"
    assert result["facts_sufficient"] is False
    assert "已经修复" not in result["reply_draft"]
    assert "【位置】" in result["reply_draft"]


def test_analyze_llm_unavailable_degrade_fields(monkeypatch, _mute_usage):
    ticket = _Ticket(status="pending")
    service = AiService(_Repo(ticket), _Audit(), _Settings())

    class _Off:
        available = False
        provider = "deepseek"
        model = "off"

        def complete(self, *_a, **_k):
            raise AssertionError("should not call LLM when unavailable")

    monkeypatch.setattr("app.services.ai_service.get_llm_client", lambda: _Off())
    result = service.analyze(ticket.ticket_id, [CAP_TRIAGE_ASSISTANT], _principal("agent"),
                             capability=CAP_TRIAGE_ASSISTANT)[0].result
    assert result["provider"] == "rules"
    assert result["model"] == "rules"
    assert result["degraded"] is True
    assert result["degrade_reason"] == "llm_unavailable"
    assert result["usage_unavailable"] is True


def test_analyze_valid_llm_triage_persists_without_degrade(monkeypatch, _mute_usage):
    ticket = _Ticket(status="pending")
    service = AiService(_Repo(ticket), _Audit(), _Settings())
    good = _valid_triage()
    monkeypatch.setattr(
        "app.services.ai_service.get_llm_client",
        lambda: _FakeLlm(LlmResult(
            success=True, data=good, model="mock-model",
            usage=LlmUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7),
        )),
    )
    result = service.analyze(ticket.ticket_id, [CAP_TRIAGE_ASSISTANT], _principal("agent"),
                             capability=CAP_TRIAGE_ASSISTANT)[0].result
    assert result["degraded"] is False
    assert result["degrade_reason"] is None
    assert result["provider"] == "deepseek"
    assert result["model"] == "mock-model"
    assert result["usage_unavailable"] is False
    assert result["advisory_only"] is True
