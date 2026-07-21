import unittest
import asyncio
import os
from datetime import datetime
from unittest.mock import AsyncMock, patch

from rasa_sdk import Tracker
from rasa_sdk.executor import CollectingDispatcher

from actions.public_request import (
    ActionCreatePublicRequest,
    ActionPrepareRequestSummary,
    ActionQueryPublicRequest,
    ActionResetPublicRequest,
    ActionStartPublicRequest,
)
from actions.ticket_store import InMemoryTicketStore, ticket_store
from actions.ticket_gateway import (
    TicketBusinessError,
    TicketConnectionError,
    TicketNotFoundError,
    TicketTimeoutError,
    _memory_gateway,
)


def make_tracker(slots=None, text="", entities=None, intent="provide_information"):
    return Tracker(
        sender_id="unit-test",
        slots=slots or {},
        latest_message={
            "text": text,
            "intent": {"name": intent},
            "entities": entities or [],
        },
        events=[],
        paused=False,
        followup_action=None,
        active_loop={},
        latest_action_name=None,
    )


def slot_values(events):
    return {
        event.get("name"): event.get("value")
        for event in events
        if event.get("event") == "slot"
    }


class TicketStoreTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 13, 9, 30, 5)
        self.store = InMemoryTicketStore(clock=lambda: self.now)

    def test_ticket_id_generation_is_sequential_and_formatted(self):
        first = self.store.create_ticket("投诉", "路灯不亮", "幸福路")
        second = self.store.create_ticket("建议", "增加路灯", "幸福路")
        self.assertEqual("QT202607130001", first["ticket_id"])
        self.assertEqual("QT202607130002", second["ticket_id"])

    def test_create_and_get_ticket_preserves_fields(self):
        created = self.store.create_ticket(
            "求助",
            "老人需要上门办理",
            "和平社区",
            event="上门办理",
            time="明天",
            target="社区工作人员",
            contact="13800138000",
        )
        found = self.store.get_ticket(created["ticket_id"])
        self.assertEqual(created, found)
        self.assertEqual("待受理", found["status"])
        self.assertEqual("2026-07-13T09:30:05", found["created_at"])

    def test_get_nonexistent_ticket_returns_none(self):
        self.assertIsNone(self.store.get_ticket("QT202607139999"))

    def test_query_tickets_filters_deterministically(self):
        self.store.create_ticket("投诉", "垃圾未清", "幸福社区")
        self.store.create_ticket("建议", "增加座椅", "幸福社区")
        matches = self.store.query_tickets(request_type="投诉")
        self.assertEqual(1, len(matches))
        self.assertEqual("垃圾未清", matches[0]["description"])

    def test_update_status_is_deterministic(self):
        created = self.store.create_ticket("咨询", "居住证材料", "不适用")
        initial = self.store.get_ticket(created["ticket_id"])
        self.assertEqual("待受理", initial["status"])
        updated = self.store.update_ticket_status(created["ticket_id"], "办理中")
        self.assertEqual("办理中", updated["status"])
        self.assertEqual("办理中", self.store.get_ticket(created["ticket_id"])["status"])


class PublicRequestActionTest(unittest.TestCase):
    def setUp(self):
        os.environ["TICKET_BACKEND_MODE"] = "memory"
        ticket_store.clear()
        _memory_gateway.clear()

    def test_summary_formats_optional_empty_fields(self):
        dispatcher = CollectingDispatcher()
        tracker = make_tracker(
            {
                "request_type": "咨询",
                "description": "办理居住证需要什么材料",
                "location": "不适用",
                "time": None,
                "target": None,
                "contact": None,
            }
        )
        events = ActionPrepareRequestSummary().run(dispatcher, tracker, {})
        message = dispatcher.messages[0]["text"]
        self.assertIn("发生时间：未提供", message)
        self.assertIn("涉及对象：未提供", message)
        self.assertIn("联系方式：未提供", message)
        self.assertNotIn("None", message)
        self.assertTrue(slot_values(events)["confirmation_pending"])

    def test_start_request_keeps_duckling_time_as_readable_chinese(self):
        tracker = make_tracker(
            text="昨天晚上人民广场施工噪声很大",
            intent="submit_complaint",
            entities=[
                {
                    "entity": "time",
                    "text": "昨天晚上",
                    "value": {
                        "from": "2026-07-12T18:00:00+08:00",
                        "to": "2026-07-13T00:00:00+08:00",
                    },
                    "extractor": "DucklingEntityExtractor",
                }
            ],
        )
        events = ActionStartPublicRequest().run(
            CollectingDispatcher(), tracker, {}
        )
        self.assertEqual("昨天晚上", slot_values(events)["time"])

    def test_generic_start_request_does_not_become_description(self):
        tracker = make_tracker(text="/submit_complaint", intent="submit_complaint")
        events = ActionStartPublicRequest().run(CollectingDispatcher(), tracker, {})
        self.assertEqual("投诉", slot_values(events)["request_type"])
        self.assertIsNone(slot_values(events)["description"])

    def test_start_request_normalizes_location_and_rejects_generic_institution(self):
        normalized = make_tracker(
            text="建议在云河区政务中心增加窗口",
            intent="submit_suggestion",
            entities=[{
                "entity": "location", "value": "建议在云河区政务中心",
                "extractor": "RegexEntityExtractor",
            }],
        )
        events = ActionStartPublicRequest().run(CollectingDispatcher(), normalized, {})
        self.assertEqual("云河区政务中心", slot_values(events)["location"])

        generic = make_tracker(
            text="希望医院提供大字模式",
            intent="submit_suggestion",
            entities=[{
                "entity": "location", "value": "希望医院",
                "extractor": "RegexEntityExtractor",
            }],
        )
        generic_events = ActionStartPublicRequest().run(CollectingDispatcher(), generic, {})
        self.assertNotIn("location", slot_values(generic_events))

    def test_create_rejects_missing_required_slot(self):
        dispatcher = CollectingDispatcher()
        tracker = make_tracker(
            {"request_type": "投诉", "description": "垃圾未清", "location": None}
        )
        events = asyncio.run(ActionCreatePublicRequest().run(dispatcher, tracker, {}))
        self.assertIn("发生地点", dispatcher.messages[0]["text"])
        self.assertFalse(slot_values(events)["confirmation_pending"])
        self.assertEqual([], ticket_store.query_tickets())

    def test_create_clears_form_slots_and_keeps_last_ticket_id(self):
        dispatcher = CollectingDispatcher()
        tracker = make_tracker(
            {
                "request_type": "投诉",
                "description": "垃圾三天无人清理",
                "location": "幸福社区",
                "time": "三天",
                "target": "小区垃圾",
                "contact": None,
            }
        )
        events = asyncio.run(ActionCreatePublicRequest().run(dispatcher, tracker, {}))
        values = slot_values(events)
        self.assertRegex(values["last_ticket_id"], r"^QT\d{12}$")
        self.assertIsNone(values["request_type"])
        self.assertIsNone(values["description"])
        self.assertIsNone(values["location"])
        ticket = ticket_store.get_ticket(values["last_ticket_id"])
        self.assertEqual("待受理", ticket["status"])
        self.assertIn(values["last_ticket_id"], dispatcher.messages[0]["text"])

    def test_create_service_exception_has_safe_fallback(self):
        dispatcher = CollectingDispatcher()
        tracker = make_tracker(
            {"request_type": "投诉", "description": "垃圾未清", "location": "社区"}
        )
        gateway = AsyncMock()
        gateway.create_ticket.side_effect = TicketConnectionError("boom")
        with patch("actions.public_request.get_ticket_gateway", return_value=gateway):
            asyncio.run(ActionCreatePublicRequest().run(dispatcher, tracker, {}))
        self.assertIn("无法连接", dispatcher.messages[0]["text"])
        self.assertNotIn("boom", dispatcher.messages[0]["text"])

    def test_query_existing_and_nonexistent_ticket(self):
        created = ticket_store.create_ticket("建议", "增加公交站", "幸福路")
        dispatcher = CollectingDispatcher()
        tracker = make_tracker({"ticket_id": created["ticket_id"]})
        asyncio.run(ActionQueryPublicRequest().run(dispatcher, tracker, {}))
        self.assertIn("待受理", dispatcher.messages[0]["text"])

        missing_dispatcher = CollectingDispatcher()
        missing_tracker = make_tracker({"ticket_id": "QT202607139999"})
        asyncio.run(ActionQueryPublicRequest().run(missing_dispatcher, missing_tracker, {}))
        self.assertIn("未找到", missing_dispatcher.messages[0]["text"])

    def test_query_without_ticket_id_asks_for_it(self):
        dispatcher = CollectingDispatcher()
        events = asyncio.run(ActionQueryPublicRequest().run(dispatcher, make_tracker({}), {}))
        self.assertIn("请提供", dispatcher.messages[0]["text"])
        self.assertTrue(slot_values(events)["awaiting_ticket_id"])

    def test_query_service_exception_has_safe_fallback(self):
        dispatcher = CollectingDispatcher()
        tracker = make_tracker({"ticket_id": "QT202607130001"})
        gateway = AsyncMock()
        gateway.get_ticket.side_effect = TicketConnectionError("boom")
        with patch("actions.public_request.get_ticket_gateway", return_value=gateway):
            asyncio.run(ActionQueryPublicRequest().run(dispatcher, tracker, {}))
        self.assertIn("无法连接", dispatcher.messages[0]["text"])

    def test_create_timeout_and_business_error_are_distinguished(self):
        tracker = make_tracker(
            {"request_type": "投诉", "description": "垃圾未清", "location": "社区"}
        )
        for error, expected in [
            (TicketTimeoutError("slow"), "超时"),
            (TicketBusinessError("地点格式不正确", "VALIDATION_ERROR"), "业务校验"),
        ]:
            dispatcher = CollectingDispatcher()
            gateway = AsyncMock()
            gateway.create_ticket.side_effect = error
            with patch("actions.public_request.get_ticket_gateway", return_value=gateway):
                asyncio.run(ActionCreatePublicRequest().run(dispatcher, tracker, {}))
            self.assertIn(expected, dispatcher.messages[0]["text"])

    def test_duplicate_submit_uses_same_idempotency_key(self):
        tracker = make_tracker(
            {
                "request_type": "求助", "description": "需要上门办理",
                "location": "社区", "idempotency_key": "fixed-idempotency-key",
            }
        )
        first = CollectingDispatcher()
        second = CollectingDispatcher()
        asyncio.run(ActionCreatePublicRequest().run(first, tracker, {}))
        asyncio.run(ActionCreatePublicRequest().run(second, tracker, {}))
        first_id = next(iter(ticket_store.query_tickets()))["ticket_id"]
        self.assertEqual(1, len(ticket_store.query_tickets()))
        self.assertIn(first_id, first.messages[0]["text"])
        self.assertIn(first_id, second.messages[0]["text"])

    def test_reset_only_clears_public_request_slots(self):
        dispatcher = CollectingDispatcher()
        tracker = make_tracker({"request_type": "投诉", "email": "legacy@example.com"})
        events = ActionResetPublicRequest().run(dispatcher, tracker, {})
        values = slot_values(events)
        self.assertIsNone(values["request_type"])
        self.assertNotIn("email", values)
        self.assertIn("已取消", dispatcher.messages[0]["text"])


if __name__ == "__main__":
    unittest.main()
