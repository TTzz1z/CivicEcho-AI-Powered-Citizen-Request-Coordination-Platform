"""Legacy Helpdesk incident actions.

These actions back the legacy ``open_incident_form`` / ``incident_status_form``
flows retained from the original Rasa Helpdesk demo. They must NOT emit English
text to citizens — all user-facing strings are Chinese. The backend ticket
system is the source of truth; ServiceNow is only used when explicitly
configured and reachable.
"""
import logging
from typing import Dict, Text, Any, List

from rasa_sdk import Tracker
from rasa_sdk.executor import CollectingDispatcher, Action
from rasa_sdk.forms import FormValidationAction
from rasa_sdk.events import AllSlotsReset, SlotSet
from actions.snow import SnowAPI


logger = logging.getLogger(__name__)
vers = "vers: 0.2.0, date: 2026-07-20"
logger.debug(vers)

snow = SnowAPI()
localmode = snow.localmode
logger.debug(f"Local mode: {snow.localmode}")


class ActionAskEmail(Action):
    def name(self) -> Text:
        return "action_ask_email"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict]:
        if tracker.get_slot("previous_email"):
            dispatcher.utter_message(template=f"utter_ask_use_previous_email",)
        else:
            dispatcher.utter_message(template=f"utter_ask_email")
        return []


def _validate_email(
    value: Text,
    dispatcher: CollectingDispatcher,
    tracker: Tracker,
    domain: Dict[Text, Any],
) -> Dict[Text, Any]:
    """Validate email is in ticket system."""
    if not value:
        return {"email": None, "previous_email": None}
    elif isinstance(value, bool):
        value = tracker.get_slot("previous_email")

    if localmode:
        return {"email": value}

    results = snow.email_to_sysid(value)
    caller_id = results.get("caller_id")

    if caller_id:
        return {"email": value, "caller_id": caller_id}
    elif isinstance(caller_id, list):
        dispatcher.utter_message(template="utter_no_email")
        return {"email": None}
    else:
        # Surface backend error in Chinese; snow.py may return English debug
        # info, so we wrap with a Chinese prefix and avoid leaking stack traces.
        err = results.get("error") or "无法校验该邮箱"
        dispatcher.utter_message(text=f"校验邮箱时出现问题：{err}")
        return {"email": None}


class ValidateOpenIncidentForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_open_incident_form"

    def validate_email(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate email is in ticket system."""
        return _validate_email(value, dispatcher, tracker, domain)

    def validate_priority(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate priority is a valid value."""

        if value.lower() in snow.priority_db():
            return {"priority": value}
        else:
            dispatcher.utter_message(template="utter_no_priority")
            return {"priority": None}


class ActionOpenIncident(Action):
    def name(self) -> Text:
        return "action_open_incident"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict]:
        """Create an incident and return details or
        if localmode return incident details as if incident
        was created
        """

        priority = tracker.get_slot("priority")
        email = tracker.get_slot("email")
        problem_description = tracker.get_slot("problem_description")
        incident_title = tracker.get_slot("incident_title")
        confirm = tracker.get_slot("confirm")
        if not confirm:
            dispatcher.utter_message(
                template="utter_incident_creation_canceled"
            )
            return [AllSlotsReset(), SlotSet("previous_email", email)]

        if localmode:
            message = (
                f"已收到您的诉求信息（本地演示模式）：\n"
                f"联系邮箱：{email}\n"
                f"问题描述：{problem_description}\n"
                f"问题概要：{incident_title}\n"
                f"紧急程度：{priority}\n"
                f"请前往“我的工单”查看后续办理进度。"
            )
        else:
            snow_priority = snow.priority_db().get(priority)
            response = snow.create_incident(
                description=problem_description,
                short_description=incident_title,
                priority=snow_priority,
                email=email,
            )
            incident_number = (
                response.get("content", {}).get("result", {}).get("number")
            )
            if incident_number:
                message = (
                    f"已为您创建工单 {incident_number}，相关部门会尽快与您联系跟进。"
                )
            else:
                err = response.get("error") or "未知错误"
                message = (
                    f"提交工单时出现问题，请稍后重试或拨打 12345 反映。"
                    f"（详情：{err}）"
                )
        dispatcher.utter_message(message)
        return [AllSlotsReset(), SlotSet("previous_email", email)]


class IncidentStatusForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_incident_status_form"

    def validate_email(
        self,
        value: Text,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate email is in ticket system."""
        return _validate_email(value, dispatcher, tracker, domain)


class ActionCheckIncidentStatus(Action):
    def name(self) -> Text:
        return "action_check_incident_status"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict]:
        """Look up all incidents associated with email address
           and return status of each"""

        email = tracker.get_slot("email")

        incident_states = {
            "New": "等待受理",
            "In Progress": "正在办理",
            "On Hold": "已暂停",
            "Closed": "已办结",
        }
        if localmode:
            status = incident_states["New"]
            message = (
                f"当前为本地演示模式。邮箱 {email} 对应的最新工单状态为：{status}。"
            )
        else:
            incidents_result = snow.retrieve_incidents(email)
            incidents = incidents_result.get("incidents")
            if incidents:
                message = "\n".join(
                    [
                        f'工单 {i.get("number")}：'
                        f'"{i.get("short_description")}"，'
                        f'创建于 {i.get("opened_at")}，'
                        f'当前状态：{incident_states.get(i.get("incident_state"), "未知")}'
                        for i in incidents
                    ]
                )
            else:
                err = incidents_result.get("error") or "未找到相关工单"
                message = f"查询工单状态时出现问题：{err}"

        dispatcher.utter_message(message)
        return [AllSlotsReset(), SlotSet("previous_email", email)]
