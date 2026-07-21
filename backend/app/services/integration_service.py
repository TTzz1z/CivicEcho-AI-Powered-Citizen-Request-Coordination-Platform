import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

from ..authorization import AuthorizationPolicy, Principal
from ..errors import BusinessError, PermissionDenied, TicketNotFound
from ..models import UserModel
from ..schemas import IntegrationStatusRead, TokenResponse
from ..security import create_access_token, hash_password


class JsonHttpClient:
    def __init__(self, timeout: int):
        self.timeout = timeout

    def request(self, method: str, url: str, token: str | None = None, payload=None, form=None):
        headers = {"Accept": "application/json", "User-Agent": "Tingting-Integration/1.0"}
        data = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urllib.parse.urlencode(form).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return response.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise BusinessError("INTEGRATION_HTTP_ERROR", "外部平台返回错误", 502, {"status": exc.code, "detail": detail[:500]}) from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise BusinessError("INTEGRATION_UNAVAILABLE", "外部平台暂不可用", 503, {"reason": str(exc)[:300]}) from exc


class IntegrationService:
    def __init__(self, repository, audit, users, departments, settings, http=None):
        self.repository = repository
        self.audit = audit
        self.users = users
        self.departments = departments
        self.settings = settings
        self.http = http or JsonHttpClient(settings.integration_timeout_seconds)

    @staticmethod
    def _admin(principal: Principal):
        if principal.role != "admin":
            raise PermissionDenied()

    def statuses(self, principal: Principal):
        self._admin(principal)
        definitions = [
            ("oidc", self.settings.oidc_enabled, bool(self.settings.oidc_issuer and self.settings.oidc_client_id), "OIDC"),
            ("directory", bool(self.settings.directory_api_url), bool(self.settings.directory_api_url and self.settings.directory_api_token), "HTTP API"),
            ("work_order", self.settings.work_order_platform != "disabled", bool(self.settings.work_order_api_url and self.settings.work_order_api_token), self.settings.work_order_platform),
            ("sms", bool(self.settings.sms_api_url), bool(self.settings.sms_api_url and self.settings.sms_api_token), "HTTP API"),
            ("map", bool(self.settings.map_api_url), bool(self.settings.map_api_url and self.settings.map_api_token), "HTTP API"),
            ("division", bool(self.settings.division_api_url), bool(self.settings.division_api_url and self.settings.division_api_token), "HTTP API"),
            ("logging", bool(self.settings.central_log_endpoint), bool(self.settings.central_log_endpoint), "JSON/HTTP"),
            ("monitoring", bool(self.settings.monitoring_endpoint), bool(self.settings.monitoring_endpoint), "scrape/webhook"),
        ]
        return [IntegrationStatusRead(integration_type=kind, enabled=enabled, configured=configured, mode=mode,
                                      message="已配置" if configured else "未配置，使用本地安全降级")
                for kind, enabled, configured, mode in definitions]

    def oidc_config(self):
        issuer = (self.settings.oidc_issuer or "").rstrip("/")
        authorization_endpoint = None
        if self.settings.oidc_enabled and issuer:
            _, discovery = self.http.request("GET", f"{issuer}/.well-known/openid-configuration")
            authorization_endpoint = discovery.get("authorization_endpoint")
        return {
            "enabled": self.settings.oidc_enabled,
            "issuer": issuer or None,
            "client_id": self.settings.oidc_client_id,
            "redirect_uri": self.settings.oidc_redirect_uri,
            "scopes": self.settings.oidc_scopes,
            "authorization_endpoint": authorization_endpoint,
        }

    def oidc_exchange(self, code: str, redirect_uri: str):
        if not self.settings.oidc_enabled:
            raise BusinessError("OIDC_DISABLED", "统一身份认证尚未启用", 409)
        if redirect_uri != self.settings.oidc_redirect_uri:
            raise BusinessError("OIDC_REDIRECT_MISMATCH", "OIDC 回调地址不匹配", 400)
        issuer = self.settings.oidc_issuer.rstrip("/")
        _, discovery = self.http.request("GET", f"{issuer}/.well-known/openid-configuration")
        _, token_data = self.http.request("POST", discovery["token_endpoint"], form={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": self.settings.oidc_client_id, "client_secret": self.settings.oidc_client_secret,
        })
        _, claims = self.http.request("GET", discovery["userinfo_endpoint"], token=token_data.get("access_token"))
        subject = str(claims.get("sub") or "")
        if not subject:
            raise BusinessError("OIDC_CLAIMS_INVALID", "统一身份认证未返回用户标识", 502)
        user = self.users.get_by_oidc_subject(subject)
        if not user:
            username = str(claims.get("preferred_username") or claims.get("email") or f"oidc_{subject}")[:100]
            user = self.users.get_by_username(username)
            if not user:
                raise BusinessError("OIDC_USER_NOT_PROVISIONED", "该统一身份账号尚未同步到人员目录", 403)
            user.oidc_subject = subject
            self.users.save(user)
        if not user.is_active:
            raise PermissionDenied("账号已停用")
        self.audit.log(Principal("user", user.id, user.username, user.role, user.department_id), "oidc_login", resource_type="user", resource_id=str(user.id))
        return TokenResponse(access_token=create_access_token(user.id, user.role), expires_in=self.settings.jwt_access_token_minutes * 60)

    def sync_directory(self, principal: Principal):
        self._admin(principal)
        if not self.settings.directory_api_url or not self.settings.directory_api_token:
            raise BusinessError("DIRECTORY_NOT_CONFIGURED", "真实组织人员目录尚未配置", 409)
        event = self.repository.start("directory", "sync_users", "inbound", principal)
        try:
            code, data = self.http.request("GET", self.settings.directory_api_url, self.settings.directory_api_token)
            created = updated = skipped = 0
            for item in data.get("items", []):
                external_id = str(item.get("external_id") or "")[:255]
                username = str(item.get("username") or "")[:100]
                role = item.get("role")
                if not external_id or not username or role not in {"citizen", "agent", "department_staff", "admin"}:
                    skipped += 1
                    continue
                department = self.departments.get_by_code(item.get("department_code")) if item.get("department_code") else None
                user = self.users.get_by_directory_id(external_id) or self.users.get_by_username(username)
                if not user:
                    user = UserModel(username=username, password_hash=hash_password(str(uuid4()) + str(uuid4())),
                                     display_name=str(item.get("display_name") or username)[:100], role=role,
                                     department_id=department.id if department else None,
                                     directory_external_id=external_id, is_active=bool(item.get("is_active", True)))
                    self.users.add(user)
                    created += 1
                else:
                    user.display_name = str(item.get("display_name") or username)[:100]
                    user.role = role
                    user.department_id = department.id if department else None
                    user.directory_external_id = external_id
                    user.is_active = bool(item.get("is_active", True))
                    self.users.save(user)
                    updated += 1
            self.repository.finish(event, "success", response_code=code)
            result = {"created": created, "updated": updated, "skipped": skipped}
            self.audit.log(principal, "sync_identity_directory", resource_type="integration", resource_id=event.id, details=result)
            return result
        except Exception as exc:
            self.repository.finish(event, "failed", error_summary=str(exc))
            self.audit.log(principal, "sync_identity_directory", "failure", "integration", event.id, {"error": str(exc)})
            raise

    def sync_ticket(self, ticket_id: str, force: bool, principal: Principal):
        ticket = self.repository.ticket(ticket_id)
        if not ticket:
            raise TicketNotFound(ticket_id)
        AuthorizationPolicy.require_view(principal, ticket)
        if principal.role not in {"agent", "admin"}:
            raise PermissionDenied()
        if self.settings.work_order_platform == "disabled" or not self.settings.work_order_api_url:
            raise BusinessError("WORK_ORDER_PLATFORM_NOT_CONFIGURED", "政务工单平台尚未配置", 409)
        if ticket.external_ticket_id and not force:
            return {"ticket_id": ticket.ticket_id, "external_ticket_id": ticket.external_ticket_id, "status": ticket.external_sync_status, "replayed": True}
        payload = {
            "local_ticket_id": ticket.ticket_id, "request_type": ticket.request_type,
            "description": ticket.description, "location": ticket.location, "status": ticket.status,
            "category_id": ticket.category_id, "department_id": ticket.assigned_department_id,
            "priority": ticket.priority,
        }
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        event = self.repository.start("work_order", "upsert_ticket", "outbound", principal, "ticket", ticket.ticket_id, payload_hash)
        try:
            code, data = self.http.request("POST", self.settings.work_order_api_url, self.settings.work_order_api_token, payload=payload)
            external_id = str(data.get("id") or data.get("ticket_id") or "")[:128]
            if not external_id:
                raise BusinessError("WORK_ORDER_RESPONSE_INVALID", "外部工单平台未返回工单编号", 502)
            ticket.external_platform = self.settings.work_order_platform
            ticket.external_ticket_id = external_id
            ticket.external_sync_status = "synced"
            ticket.external_synced_at = datetime.now(timezone.utc)
            self.repository.save_ticket(ticket)
            self.repository.finish(event, "success", external_id, code)
            self.audit.log(principal, "sync_external_ticket", resource_type="ticket", resource_id=ticket.ticket_id,
                           details={"platform": ticket.external_platform, "external_id": external_id})
            return {"ticket_id": ticket.ticket_id, "external_ticket_id": external_id, "status": "synced", "replayed": False}
        except Exception as exc:
            ticket.external_sync_status = "failed"
            self.repository.save_ticket(ticket)
            self.repository.finish(event, "failed", error_summary=str(exc))
            self.audit.log(principal, "sync_external_ticket", "failure", "ticket", ticket.ticket_id, {"error": str(exc)})
            raise

    def proxy_lookup(self, kind: str, query: str, principal: Principal):
        options = {
            "map": (self.settings.map_api_url, self.settings.map_api_token, "address"),
            "division": (self.settings.division_api_url, self.settings.division_api_token, "parent_code"),
        }
        url, token, key = options[kind]
        if not url:
            raise BusinessError(f"{kind.upper()}_NOT_CONFIGURED", "外部服务尚未配置", 409)
        event = self.repository.start(kind, "lookup", "outbound", principal)
        try:
            target = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode({key: query})}"
            code, data = self.http.request("GET", target, token)
            self.repository.finish(event, "success", response_code=code)
            self.audit.log(principal, f"lookup_{kind}", resource_type="integration", resource_id=event.id)
            return data
        except Exception as exc:
            self.repository.finish(event, "failed", error_summary=str(exc))
            raise

    def metrics(self, principal: Principal):
        self._admin(principal)
        return self.repository.metrics()

    def send_sms(self, phone: str, template_code: str, parameters: dict, principal: Principal):
        self._admin(principal)
        if not self.settings.sms_api_url or not self.settings.sms_api_token:
            raise BusinessError("SMS_NOT_CONFIGURED", "短信服务尚未配置", 409)
        payload = {"phone": phone, "template_code": template_code, "parameters": parameters}
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        event = self.repository.start("sms", "send_template", "outbound", principal, "sms_template", template_code, payload_hash)
        try:
            code, data = self.http.request("POST", self.settings.sms_api_url, self.settings.sms_api_token, payload=payload)
            message_id = str(data.get("message_id") or data.get("id") or "")[:255] or None
            self.repository.finish(event, "success", message_id, code)
            self.audit.log(principal, "send_sms_template", resource_type="integration", resource_id=event.id,
                           details={"template_code": template_code, "phone": f"{phone[:3]}****{phone[-4:]}"})
            return {"delivery_status": "accepted", "message_id": message_id}
        except Exception as exc:
            self.repository.finish(event, "failed", error_summary=str(exc))
            self.audit.log(principal, "send_sms_template", "failure", "integration", event.id,
                           {"template_code": template_code, "error": str(exc)})
            raise

    def probe_observability(self, kind: str, principal: Principal):
        self._admin(principal)
        if kind not in {"logging", "monitoring"}:
            raise BusinessError("INVALID_INTEGRATION_TYPE", "只允许探测日志或监控连接器", 422)
        url = self.settings.central_log_endpoint if kind == "logging" else self.settings.monitoring_endpoint
        token = self.settings.central_log_token if kind == "logging" else self.settings.monitoring_token
        if not url:
            raise BusinessError(f"{kind.upper()}_NOT_CONFIGURED", "可观测性平台尚未配置", 409)
        event = self.repository.start(kind, "probe", "outbound", principal)
        payload = {"event": "tingting_integration_probe", "service": self.settings.app_name,
                   "status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
        try:
            code, data = self.http.request("POST", url, token, payload=payload)
            self.repository.finish(event, "success", response_code=code)
            self.audit.log(principal, f"probe_{kind}_platform", resource_type="integration", resource_id=event.id)
            return {"status": "ok", "response": data}
        except Exception as exc:
            self.repository.finish(event, "failed", error_summary=str(exc))
            self.audit.log(principal, f"probe_{kind}_platform", "failure", "integration", event.id, {"error": str(exc)})
            raise
