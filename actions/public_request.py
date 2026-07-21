"""Custom actions for the Chinese public-request conversation flow."""

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import FollowupAction, SlotSet
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.forms import FormValidationAction

from actions.ticket_gateway import (
    TicketBusinessError,
    TicketConnectionError,
    TicketGatewayError,
    TicketNotFoundError,
    TicketTimeoutError,
    get_ticket_gateway,
    set_request_id,
)


logger = logging.getLogger(__name__)

REQUEST_TYPE_BY_INTENT = {
    "submit_complaint": "投诉",
    "submit_suggestion": "建议",
    "policy_consultation": "咨询",
    "request_help": "求助",
}

PUBLIC_REQUEST_SLOTS = (
    "request_type",
    "description",
    "location",
    "event",
    "time",
    "time_start",
    "time_end",
    "time_precision",
    "time_timezone",
    "target",
    "contact",
    "ticket_id",
    "confirmation_pending",
    "correction_pending",
    "awaiting_ticket_id",
    "idempotency_key",
)


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _display(value: Any) -> str:
    return _clean(value) or "未提供"


def _latest_entities(tracker: Tracker) -> Dict[str, Any]:
    entities = tracker.latest_message.get("entities", []) or []
    values: Dict[str, Any] = {}
    location_candidates = []
    for entity in entities:
        entity_name = entity.get("entity")
        if entity_name not in PUBLIC_REQUEST_SLOTS:
            continue
        value = entity.get("value")
        if entity_name == "time" and entity.get("extractor") == "DucklingEntityExtractor":
            duckling_value = value
            values["time"] = entity.get("text") or value
            if isinstance(duckling_value, dict):
                start = duckling_value.get("from")
                end = duckling_value.get("to")
                if isinstance(start, dict):
                    start = start.get("value")
                if isinstance(end, dict):
                    end = end.get("value")
                if start:
                    values["time_start"] = start
                if end:
                    values["time_end"] = end
                values["time_precision"] = "range" if end else "instant"
                values["time_timezone"] = "Asia/Shanghai"
            continue
        if entity_name == "location":
            candidate = _clean(value)
            if candidate:
                candidate = re.sub(
                    r"^(?:建议|希望|可以|最好|能否|请|我想)(?:要)?(?:在)?",
                    "",
                    candidate,
                ).strip()
                if candidate not in {"医院", "学校", "社区", "小区", "农村", "村"}:
                    location_candidates.append(
                        (entity.get("extractor") == "RegexEntityExtractor", len(candidate), candidate)
                    )
            continue
        values[entity_name] = value
    if location_candidates:
        values["location"] = max(location_candidates)[2]
    return values


class ActionStartPublicRequest(Action):
    def name(self) -> Text:
        return "action_start_public_request"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        intent = tracker.latest_message.get("intent", {}).get("name")
        description = _clean(tracker.latest_message.get("text"))
        if description and (description.startswith("/") or description in {
            "我要投诉", "我要提交投诉", "我要提交一条投诉", "我要建议", "我想提出建议",
            "我要咨询", "我要咨询政策", "我要求助", "我需要帮助",
        }):
            description = None
        events: List[Dict[Text, Any]] = [
            SlotSet("request_type", REQUEST_TYPE_BY_INTENT.get(intent)),
            SlotSet("description", description),
            SlotSet("confirmation_pending", False),
            SlotSet("correction_pending", False),
            SlotSet("idempotency_key", str(uuid.uuid4())),
        ]
        for key, value in _latest_entities(tracker).items():
            if key not in {"request_type", "description", "ticket_id"}:
                events.append(SlotSet(key, value))
        return events


class ValidatePublicRequestForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_public_request_form"

    def validate_request_type(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        normalized = _clean(value)
        aliases = {
            "投诉": "投诉",
            "建议": "建议",
            "咨询": "咨询",
            "求助": "求助",
            "帮忙": "求助",
        }
        if normalized in aliases:
            return {"request_type": aliases[normalized]}
        dispatcher.utter_message(text="请选择投诉、建议、咨询或求助中的一种。")
        return {"request_type": None}

    def validate_description(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        normalized = _clean(value)
        if normalized:
            return {"description": normalized}
        dispatcher.utter_message(text="诉求描述不能为空，请再说明一下具体情况。")
        return {"description": None}

    def validate_location(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        normalized = _clean(value)
        if normalized:
            return {"location": normalized}
        dispatcher.utter_message(text="请提供发生地点；咨询事项可回复“不适用”。")
        return {"location": None}


class ActionPrepareRequestSummary(Action):
    def name(self) -> Text:
        return "action_prepare_request_summary"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        summary = (
            "请确认以下诉求信息：\n"
            f"- 诉求类型：{_display(tracker.get_slot('request_type'))}\n"
            f"- 诉求描述：{_display(tracker.get_slot('description'))}\n"
            f"- 发生地点：{_display(tracker.get_slot('location'))}\n"
            f"- 发生时间：{_display(tracker.get_slot('time'))}\n"
            f"- 涉及对象：{_display(tracker.get_slot('target'))}\n"
            f"- 联系方式：{_display(tracker.get_slot('contact'))}"
        )
        dispatcher.utter_message(
            text=summary,
            buttons=[
                {"title": "确认创建", "payload": "/affirm"},
                {"title": "修改信息", "payload": "/deny"},
                {"title": "取消登记", "payload": "/cancel_request"},
            ],
        )
        return [
            SlotSet("confirmation_pending", True),
            SlotSet("correction_pending", False),
            FollowupAction("action_listen"),
        ]


class ActionRequestPublicRequestCorrection(Action):
    def name(self) -> Text:
        return "action_request_public_request_correction"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(
            text=(
                "好的，请告诉我需要修改哪一项以及新内容，"
                "例如“地点改成幸福路社区”或“描述改成路灯连续三晚不亮”。"
            )
        )
        return [
            SlotSet("confirmation_pending", False),
            SlotSet("correction_pending", True),
            FollowupAction("action_listen"),
        ]


class ActionApplyPublicRequestCorrection(Action):
    def name(self) -> Text:
        return "action_apply_public_request_correction"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        text = _clean(tracker.latest_message.get("text")) or ""
        updates = _latest_entities(tracker)
        patterns = {
            "location": r"(?:地点|地址)(?:改成|改为|是|：|:)\s*(.+)",
            "description": r"(?:描述|诉求|情况)(?:改成|改为|是|：|:)\s*(.+)",
            "contact": r"(?:联系方式|电话)(?:改成|改为|是|：|:)\s*(.+)",
            "time": r"(?:时间)(?:改成|改为|是|：|:)\s*(.+)",
            "target": r"(?:对象|涉及对象)(?:改成|改为|是|：|:)\s*(.+)",
            "request_type": r"(?:类型)(?:改成|改为|是|：|:)\s*(投诉|建议|咨询|求助)",
        }
        for slot_name, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                updates[slot_name] = match.group(1).strip("，。 ")

        updates = {
            key: value
            for key, value in updates.items()
            if key in PUBLIC_REQUEST_SLOTS and _clean(value)
        }
        if not updates:
            dispatcher.utter_message(
                text="我还没识别出要修改的项目，请按“项目改成新内容”的方式说明。"
            )
            return [
                SlotSet("correction_pending", True),
                FollowupAction("action_listen"),
            ]

        return [
            *[SlotSet(key, value) for key, value in updates.items()],
            SlotSet("correction_pending", True),
        ]


class ActionCreatePublicRequest(Action):
    def name(self) -> Text:
        return "action_create_public_request"

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        set_request_id((tracker.latest_message.get("metadata") or {}).get("request_id"))
        required = {
            "诉求类型": _clean(tracker.get_slot("request_type")),
            "诉求描述": _clean(tracker.get_slot("description")),
            "发生地点": _clean(tracker.get_slot("location")),
        }
        missing = [label for label, value in required.items() if not value]
        if missing:
            dispatcher.utter_message(
                text=f"暂时无法创建工单，缺少必填信息：{'、'.join(missing)}。"
            )
            return [
                SlotSet("confirmation_pending", False),
                FollowupAction("action_listen"),
            ]

        idempotency_key = _clean(tracker.get_slot("idempotency_key")) or str(uuid.uuid4())
        payload = {
            "idempotency_key": idempotency_key,
            "request_type": required["诉求类型"],
            "description": required["诉求描述"],
            "location": required["发生地点"],
            "event": _clean(tracker.get_slot("event")),
            "occurred_at": _clean(tracker.get_slot("time")),
            "occurred_at_text": _clean(tracker.get_slot("time")),
            "occurred_at_start": _clean(tracker.get_slot("time_start")),
            "occurred_at_end": _clean(tracker.get_slot("time_end")),
            "occurred_at_precision": _clean(tracker.get_slot("time_precision")),
            "timezone": _clean(tracker.get_slot("time_timezone")) or "Asia/Shanghai",
            "target": _clean(tracker.get_slot("target")),
            "contact": _clean(tracker.get_slot("contact")),
            "source": "rasa",
            "creator_reference": tracker.sender_id,
        }
        try:
            ticket = await get_ticket_gateway().create_ticket(payload)
        except TicketTimeoutError:
            logger.warning("Ticket backend timed out while creating a ticket")
            dispatcher.utter_message(text="工单服务响应超时，诉求尚未确认创建，请稍后重试。")
        except TicketConnectionError:
            logger.warning("Could not connect to ticket backend")
            dispatcher.utter_message(text="暂时无法连接工单服务，诉求尚未创建，请稍后重试。")
        except TicketBusinessError as exc:
            logger.info("Ticket backend rejected create request: %s", exc.code)
            dispatcher.utter_message(text=f"工单信息未通过业务校验：{exc}。请修改后重试。")
        except TicketGatewayError:
            logger.exception("Ticket backend returned an unexpected response")
            dispatcher.utter_message(text="工单服务返回异常，诉求尚未创建，请稍后重试。")
        except Exception:
            logger.exception("Unexpected error while creating public-request ticket")
            dispatcher.utter_message(text="工单服务暂时不可用，诉求尚未创建，请稍后重试。")
        else:
            dispatcher.utter_message(
                text=(
                    f"诉求工单已创建，编号：{ticket['ticket_id']}，"
                    f"当前状态：{ticket.get('status_label', ticket['status'])}。请保存该编号以便查询。"
                )
            )
            events = [SlotSet(slot, None) for slot in PUBLIC_REQUEST_SLOTS]
            events.append(SlotSet("last_ticket_id", ticket["ticket_id"]))
            events.append(FollowupAction("action_listen"))
            return events

        return [
            SlotSet("idempotency_key", idempotency_key),
            SlotSet("confirmation_pending", False),
            FollowupAction("action_listen"),
        ]


class ActionQueryPublicRequest(Action):
    def name(self) -> Text:
        return "action_query_public_request"

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        set_request_id((tracker.latest_message.get("metadata") or {}).get("request_id"))
        ticket_id = _clean(tracker.get_slot("ticket_id"))
        if not ticket_id:
            entities = _latest_entities(tracker)
            ticket_id = _clean(entities.get("ticket_id"))
        if not ticket_id:
            ticket_id = _clean(tracker.get_slot("last_ticket_id"))
        if not ticket_id:
            dispatcher.utter_message(text="请提供要查询的工单编号，例如 QT202607130001。")
            return [
                SlotSet("awaiting_ticket_id", True),
                FollowupAction("action_listen"),
            ]

        try:
            ticket = await get_ticket_gateway().get_ticket(ticket_id, tracker.sender_id)
        except TicketNotFoundError:
            dispatcher.utter_message(
                text=f"未找到编号为 {ticket_id.upper()} 的工单，请核对编号后重试。"
            )
        except TicketTimeoutError:
            logger.warning("Ticket backend timed out while querying a ticket")
            dispatcher.utter_message(text="工单查询响应超时，请稍后再试。")
        except TicketConnectionError:
            logger.warning("Could not connect to ticket backend while querying")
            dispatcher.utter_message(text="暂时无法连接工单查询服务，请稍后再试。")
        except TicketBusinessError as exc:
            logger.info("Ticket backend rejected query request: %s", exc.code)
            dispatcher.utter_message(text=f"工单查询请求未通过校验：{exc}。")
        except TicketGatewayError:
            logger.exception("Ticket backend returned an unexpected query response")
            dispatcher.utter_message(text="工单查询服务返回异常，请稍后再试。")
        except Exception:
            logger.exception("Unexpected error while querying public-request ticket")
            dispatcher.utter_message(text="工单查询服务暂时不可用，请稍后再试。")
        else:
            status_label = ticket.get("status_label", ticket["status"])
            status_notes = {
                "rejected": "该诉求未予受理，如有新材料可联系受理渠道。",
                "processing": "承办部门正在处理，请耐心等待。",
                "resolved": "承办部门已标记解决，当前等待确认。",
                "closed": "该工单已经办结。",
            }
            note = status_notes.get(ticket.get("status"), "")
            dispatcher.utter_message(text=(
                f"工单 {ticket['ticket_id']}：{ticket['request_type']}；"
                f"当前状态：{status_label}；创建时间：{ticket['created_at']}。"
                + (f"{note}" if note else "")
            ))
        return [
            SlotSet("ticket_id", None),
            SlotSet("awaiting_ticket_id", False),
            FollowupAction("action_listen"),
        ]


class ActionResetPublicRequest(Action):
    def name(self) -> Text:
        return "action_reset_public_request"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(text="已取消当前诉求登记。")
        return [
            *[SlotSet(slot, None) for slot in PUBLIC_REQUEST_SLOTS],
            FollowupAction("action_listen"),
        ]


class ActionExtractRequestDraft(Action):
    """One-shot NLU extraction: returns structured draft JSON to frontend via custom payload."""

    def name(self) -> Text:
        return "action_extract_request_draft"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        intent = tracker.latest_message.get("intent", {}).get("name")
        text = _clean(tracker.latest_message.get("text"))
        request_type = REQUEST_TYPE_BY_INTENT.get(intent)

        # Extract entities from the message
        entities = _latest_entities(tracker)

        # Build description: use raw text unless it's just a trigger phrase
        description = text
        if description and (description.startswith("/") or description in {
            "我要投诉", "我要提交投诉", "我要提交一条投诉", "我要建议", "我想提出建议",
            "我要咨询", "我要咨询政策", "我要求助", "我需要帮助",
        }):
            description = None

        # If entities contain a description override, use it
        if entities.get("description"):
            description = entities["description"]

        # Build draft
        draft = {
            "request_type": request_type,
            "description": description,
            "location": _clean(entities.get("location")),
            "occurred_at_text": _clean(entities.get("time")),
            "target": _clean(entities.get("target")),
            "contact": _clean(entities.get("contact")),
        }

        # Determine missing required fields
        missing = []
        if not draft["request_type"]:
            missing.append("request_type")
        if not draft["description"] or len(draft["description"].strip()) < 4:
            missing.append("description")
        if not draft["location"]:
            missing.append("location")

        # Optional but recommended fields
        if not draft["occurred_at_text"]:
            missing.append("occurred_at_text")
        if not draft["target"]:
            missing.append("target")

        dispatcher.utter_message(
            text="我已识别到您的诉求信息，请在工单草稿面板中核对并补充缺失项。",
            json={
                "type": "draft_extracted",
                "draft": draft,
                "missing": missing,
            },
        )

        # Clean up old form slots, do NOT activate any form
        return [
            *[SlotSet(slot, None) for slot in PUBLIC_REQUEST_SLOTS],
            SlotSet("request_type", request_type),
            SlotSet("description", description),
            SlotSet("confirmation_pending", False),
            SlotSet("correction_pending", False),
            FollowupAction("action_listen"),
        ]
