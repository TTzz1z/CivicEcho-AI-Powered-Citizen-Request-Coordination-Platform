import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app import llm_client
from app.authorization import Principal
from app.services import orchestrator_service


@pytest.mark.parametrize(
    ("override", "error", "reason"),
    [
        ({"confidence": None}, None, "invalid_classification"),
        ({"in_domain": "false"}, None, "invalid_classification"),
        ({}, TimeoutError("model fixture timeout"), "TimeoutError"),
        ({}, None, None),
    ],
)
def test_provider_classification_validates_values_and_records_fallback(monkeypatch, override, error, reason):
    content = {
        "route": "general_chat",
        "primary_intent": "help",
        "confidence": 0.91,
        "in_domain": True,
    } | override

    def model_response(*_):
        if error:
            raise error
        return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()

    monkeypatch.setattr(llm_client, "read_model_response", model_response)
    recorder = Mock()
    monkeypatch.setattr(orchestrator_service, "AiUsageRecorder", lambda _: recorder)
    service = orchestrator_service.OrchestratorService()
    service.llm = llm_client.LlmClient()
    service.llm.api_key = "stub"
    monkeypatch.setattr(service.guard, "_budget_check", lambda *_: (False, ""))
    monkeypatch.setattr(service, "_rule_detect", lambda *_: None)
    monkeypatch.setattr(service, "_out_of_domain_detect", lambda *_: None)

    principal = Principal("user", 444, "fixture", "citizen", None)
    result = service.process(
        "请问社区相关事务", {"role": "citizen", "user_id": 444},
        db=Mock(), principal=principal, session_id=uuid4().hex,
    )

    assert result.degraded == bool(reason)
    assert result.degrade_reason == (reason or "")
    assert recorder.record_llm_call.call_args.kwargs["degrade_reason"] == reason
    assert recorder.record_llm_call.call_args.args[1].success == (reason is None)
