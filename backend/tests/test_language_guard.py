"""Unit tests for language_guard — no English Helpdesk residue may pass."""
from __future__ import annotations

from app.services.language_guard import (
    LANGUAGE_FALLBACK_MESSAGE,
    contains_forbidden_english,
    ensure_chinese_response,
    is_chinese_dominant,
    sanitize_rasa_messages,
)


class TestLanguageGuard:
    def test_chinese_help_passes(self):
        text = "我可以帮您：\n- 提交投诉、建议、咨询或求助事项\n- 查询工单办理进度"
        assert is_chinese_dominant(text) is True
        assert ensure_chinese_response(text) == text

    def test_english_helpdesk_help_is_blocked(self):
        text = (
            "I can help you open a service request ticket, or check the status "
            "of your open incidents. \nYou can ask me things like: \n- Open an incident"
        )
        assert contains_forbidden_english(text) is True
        assert is_chinese_dominant(text) is False
        assert ensure_chinese_response(text) == LANGUAGE_FALLBACK_MESSAGE

    def test_ticket_id_allowed(self):
        text = "工单已创建，编号：QT2026071300000001。您可以在我的工单中查看。"
        assert is_chinese_dominant(text) is True

    def test_sanitize_rasa_messages(self):
        msgs = [
            {"recipient_id": "x", "text": "您好，我是倾听助手"},
            {"recipient_id": "x", "text": "I can help you open a service request ticket"},
        ]
        out = sanitize_rasa_messages(msgs)
        assert out[0]["text"] == "您好，我是倾听助手"
        assert out[1]["text"] == LANGUAGE_FALLBACK_MESSAGE
        assert "I can help" not in out[1]["text"]
