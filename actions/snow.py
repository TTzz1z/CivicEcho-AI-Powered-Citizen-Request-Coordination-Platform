import logging
import requests
import json
import os
import pathlib
import ruamel.yaml
from typing import Dict, Text, Any

logger = logging.getLogger(__name__)

here = pathlib.Path(__file__).parent.absolute()

json_headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


class SnowAPI(object):
    """class to connect to the ServiceNow API"""

    def __init__(self):
        with open(
            here / "snow_credentials.yml", "r", encoding="utf-8"
        ) as config_file:
            snow_config = ruamel.yaml.safe_load(config_file) or {}

        self.snow_user = os.getenv(
            "SERVICENOW_USER", snow_config.get("snow_user")
        )
        self.snow_pw = os.getenv(
            "SERVICENOW_PASSWORD", snow_config.get("snow_pw")
        )
        self.snow_instance = os.getenv(
            "SERVICENOW_INSTANCE", snow_config.get("snow_instance")
        )
        localmode = os.getenv("SERVICENOW_LOCAL_MODE")
        self.localmode = (
            localmode.lower() in {"1", "true", "yes", "on"}
            if localmode is not None
            else snow_config.get("localmode", True)
        )
        self.request_timeout = float(
            os.getenv("SERVICENOW_TIMEOUT_SECONDS", "10")
        )
        self.base_api_url = (
            f"https://{self.snow_instance}/api/now"
            if self.snow_instance
            else None
        )

    def handle_request(
        self, request_method=requests.get, request_args=None
    ) -> Dict[Text, Any]:
        request_args = dict(request_args or {})
        request_args.setdefault("timeout", self.request_timeout)
        result = dict()
        try:
            response = request_method(**request_args)
            result["status_code"] = response.status_code
            if 200 <= response.status_code < 300:
                result["content"] = response.json()
            else:
                error = (
                    f"工单系统返回错误（HTTP {response.status_code}）："
                    f'{response.json().get("error",{}).get("message")}'
                )
                logger.debug(error)
                result["error"] = error
        except requests.exceptions.Timeout:
            error = "工单系统连接超时，请稍后重试"
            logger.debug(error)
            result["error"] = error
        except (requests.exceptions.RequestException, ValueError) as exc:
            error = f"工单系统请求失败：{exc}"
            logger.debug(error)
            result["error"] = error
        return result

    def email_to_sysid(self, email) -> Dict[Text, Any]:
        lookup_url = (
            f"{self.base_api_url}/table/sys_user?"
            f"sysparm_query=email={email}&sysparm_display_value=true"
        )
        request_args = {
            "url": lookup_url,
            "auth": (self.snow_user, self.snow_pw),
            "headers": json_headers,
        }
        result = self.handle_request(requests.get, request_args)
        records = result.get("content", {}).get("result")
        if not isinstance(records, list):
            result.setdefault("error", "工单系统响应格式异常")
            return result
        if len(records) == 1:
            caller_id = records[0].get("sys_id")
            result["caller_id"] = caller_id
        elif isinstance(records, list):
            result["caller_id"] = []
            result["error"] = (
                f"无法唯一确定用户：邮箱 {email} 对应多条记录"
            )
        return result

    def retrieve_incidents(self, email) -> Dict[Text, Any]:
        result = self.email_to_sysid(email)
        caller_id = result.get("caller_id")
        if caller_id:
            incident_url = (
                f"{self.base_api_url}/table/incident?"
                f"sysparm_query=caller_id={caller_id}"
                f"&sysparm_display_value=true"
            )
            request_args = {
                "url": incident_url,
                "auth": (self.snow_user, self.snow_pw),
                "headers": json_headers,
            }
            result = self.handle_request(requests.get, request_args)
            incidents = result.get(
                "content", {}  # pytype: disable=attribute-error
            ).get("result")
            if incidents:
                result["incidents"] = incidents
            elif isinstance(incidents, list):
                result["error"] = f"邮箱 {email} 暂无工单记录"
        return result

    def create_incident(
        self, description, short_description, priority, email
    ) -> Dict[Text, Any]:
        result = self.email_to_sysid(email)
        caller_id = result.get("caller_id")
        if caller_id:
            incident_url = f"{self.base_api_url}/table/incident"
            data = {
                "opened_by": caller_id,
                "short_description": short_description,
                "description": description,
                "urgency": priority,
                "caller_id": caller_id,
                "comments": description,
            }
            request_args = {
                "url": incident_url,
                "auth": (self.snow_user, self.snow_pw),
                "headers": json_headers,
                "data": json.dumps(data),
            }
            result = self.handle_request(requests.post, request_args)
        return result

    @staticmethod
    def priority_db() -> Dict[str, int]:
        """Database of supported priorities"""
        priorities = {"low": 3, "medium": 2, "high": 1}
        return priorities
