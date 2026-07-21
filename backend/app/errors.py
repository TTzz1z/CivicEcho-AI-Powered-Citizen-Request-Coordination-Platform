class BusinessError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class TicketNotFound(BusinessError):
    def __init__(self, ticket_id: str):
        super().__init__("TICKET_NOT_FOUND", f"未找到工单 {ticket_id}", 404)


class AuthenticationError(BusinessError):
    def __init__(self, message: str = "认证凭据无效或已过期"):
        super().__init__("AUTHENTICATION_REQUIRED", message, 401)


class PermissionDenied(BusinessError):
    def __init__(self, message: str = "无权执行此操作"):
        super().__init__("PERMISSION_DENIED", message, 403)


class VersionConflict(BusinessError):
    def __init__(self):
        super().__init__("VERSION_CONFLICT", "工单已被其他操作更新，请刷新后重试", 409)


class AttachmentNotFound(BusinessError):
    def __init__(self, attachment_id: str):
        super().__init__("ATTACHMENT_NOT_FOUND", f"未找到附件 {attachment_id}", 404)
