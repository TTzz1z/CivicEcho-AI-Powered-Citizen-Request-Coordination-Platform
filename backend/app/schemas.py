from datetime import datetime
from typing import Generic, Literal, Optional, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


T = TypeVar("T")
REQUEST_TYPES = {"投诉", "建议", "咨询", "求助"}
ROLES = {"citizen", "agent", "department_staff", "admin"}
STATUSES = {"pending", "accepted", "assigned", "processing", "resolved", "closed", "rejected"}
PRIORITIES = {"normal", "expedited", "urgent", "major"}
REQUESTED_PRIORITIES = PRIORITIES | {"low", "high"}
RESOLUTION_OUTCOMES = {"resolved", "partially_resolved", "unresolved"}
FEEDBACK_RATINGS = {"satisfied", "mostly_satisfied", "dissatisfied"}
REJECTION_REASONS = {
    "out_of_scope", "out_of_jurisdiction", "duplicate", "insufficient_information",
    "handled_elsewhere", "legal_or_review", "other",
}

STATUS_LABELS = {
    "pending": "待受理", "accepted": "已受理", "assigned": "已派发",
    "processing": "处理中", "resolved": "待市民确认", "closed": "已办结", "rejected": "不予受理",
}


class TicketCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    request_type: str = Field(min_length=2, max_length=16)
    description: str = Field(min_length=2, max_length=5000)
    location: str = Field(min_length=1, max_length=500)
    event: Optional[str] = Field(default=None, max_length=5000)
    occurred_at: Optional[str] = Field(default=None, max_length=200)
    occurred_at_text: Optional[str] = Field(default=None, max_length=200)
    occurred_at_start: Optional[datetime] = None
    occurred_at_end: Optional[datetime] = None
    occurred_at_precision: Optional[str] = Field(default=None, max_length=32)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    target: Optional[str] = Field(default=None, max_length=500)
    contact: Optional[str] = Field(default=None, max_length=200)
    source: str = Field(default="rasa", min_length=1, max_length=32)
    # `priority` remains accepted for old clients, but is only a citizen/requester hint.
    priority: str = "normal"
    requested_priority: Optional[str] = None
    creator_reference: Optional[str] = Field(default=None, max_length=256)

    @field_validator("request_type")
    @classmethod
    def validate_request_type(cls, value: str) -> str:
        value = value.strip()
        if value not in REQUEST_TYPES:
            raise ValueError("request_type 必须是投诉、建议、咨询或求助")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: str) -> str:
        if value not in REQUESTED_PRIORITIES:
            raise ValueError("priority 必须是 normal、expedited、urgent 或 major")
        return value

    @field_validator("requested_priority")
    @classmethod
    def validate_requested_priority(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in REQUESTED_PRIORITIES:
            raise ValueError("requested_priority 值无效")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone 必须是有效 IANA 时区") from exc
        return value

    @field_validator("description", "location", "idempotency_key", "source")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_time_range(self):
        self.occurred_at_text = self.occurred_at_text or self.occurred_at
        if self.occurred_at_start and self.occurred_at_start.utcoffset() is None:
            raise ValueError("occurred_at_start 必须包含时区")
        if self.occurred_at_end and self.occurred_at_end.utcoffset() is None:
            raise ValueError("occurred_at_end 必须包含时区")
        if self.occurred_at_start and self.occurred_at_end and self.occurred_at_start >= self.occurred_at_end:
            raise ValueError("occurred_at_end 必须晚于 occurred_at_start")
        return self


class TicketAction(BaseModel):
    remark: str = Field(min_length=1, max_length=2000)
    version: int = Field(ge=1)


class TicketAccept(TicketAction):
    category_id: Optional[int] = Field(default=None, gt=0)
    priority: str = "normal"

    @field_validator("priority")
    @classmethod
    def validate_confirmed_priority(cls, value: str) -> str:
        if value not in PRIORITIES:
            raise ValueError("priority 必须是 normal、expedited、urgent 或 major")
        return value


class TicketSlaAction(TicketAction):
    reason: Optional[str] = Field(default=None, max_length=500)


class TicketAssign(TicketAction):
    department_id: int = Field(gt=0)
    assigned_user_id: Optional[int] = Field(default=None, gt=0)


class TicketSupplementRequest(TicketAction):
    supplement_reason: str = Field(min_length=2, max_length=2000)


class TicketSupplementSubmit(TicketAction):
    supplement_content: str = Field(min_length=2, max_length=5000)


class WorkOrderCreate(BaseModel):
    version: int = Field(ge=1)
    task_type: Literal["primary", "support", "review"]
    department_id: int = Field(gt=0)
    assignee_user_id: Optional[int] = Field(default=None, gt=0)
    instructions: str = Field(min_length=2, max_length=5000)


class WorkOrderAction(BaseModel):
    version: int = Field(ge=1)
    remark: str = Field(min_length=2, max_length=2000)


class WorkOrderAssigneeUpdate(WorkOrderAction):
    assignee_user_id: int = Field(gt=0)


class WorkOrderTransfer(WorkOrderAction):
    target_department_id: int = Field(gt=0)
    assignee_user_id: Optional[int] = Field(default=None, gt=0)


class WorkOrderResult(WorkOrderAction):
    result_summary: str = Field(min_length=2, max_length=500)
    result_measures: str = Field(min_length=2, max_length=5000)
    result_outcome: str = Field(max_length=32)
    public_content: str = Field(min_length=2, max_length=5000)
    internal_note: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("result_outcome")
    @classmethod
    def validate_result_outcome(cls, value: str) -> str:
        if value not in RESOLUTION_OUTCOMES:
            raise ValueError("result_outcome 无效")
        return value


class TicketDisputeOpen(TicketAction):
    dispute_reason: str = Field(min_length=2, max_length=2000)


class TicketDisputeResolve(TicketAction):
    resolution: str = Field(min_length=2, max_length=2000)
    primary_work_order_id: Optional[str] = Field(default=None, min_length=1, max_length=36)


class TicketContactUpdate(TicketAction):
    contact: Optional[str] = Field(default=None, max_length=200)


class TicketResolve(TicketAction):
    resolution_summary: str = Field(min_length=2, max_length=500)
    resolution_measures: str = Field(min_length=2, max_length=5000)
    resolution_outcome: str = Field(max_length=32)
    public_reply: str = Field(min_length=2, max_length=5000)
    internal_note: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("resolution_outcome")
    @classmethod
    def validate_outcome(cls, value: str) -> str:
        if value not in RESOLUTION_OUTCOMES:
            raise ValueError("resolution_outcome 必须是 resolved、partially_resolved 或 unresolved")
        return value


class TicketReject(TicketAction):
    reason_code: str = Field(max_length=64)
    rejection_detail: str = Field(min_length=2, max_length=2000)
    suggested_channel: Optional[str] = Field(default=None, max_length=500)
    needs_supplement: bool = False

    @field_validator("reason_code")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if value not in REJECTION_REASONS:
            raise ValueError("reason_code 不是受支持的不予受理原因")
        return value


class TicketAdminClose(TicketAction):
    override_reason: str = Field(min_length=2, max_length=2000)


class TicketReturnToDepartment(TicketAction):
    """Agent returns a ticket to the primary department for supplement (P0-A)."""
    return_reason: str = Field(min_length=2, max_length=2000)


class TicketFeedbackCreate(BaseModel):
    version: int = Field(ge=1)
    rating: str = Field(max_length=32)
    comment: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: str) -> str:
        if value not in FEEDBACK_RATINGS:
            raise ValueError("rating 必须是 satisfied、mostly_satisfied 或 dissatisfied")
        return value

    @model_validator(mode="after")
    def require_dissatisfied_comment(self):
        if self.rating == "dissatisfied" and (not self.comment or len(self.comment.strip()) < 2):
            raise ValueError("不满意时请填写至少 2 个字符的重办原因")
        if self.comment is not None:
            self.comment = self.comment.strip() or None
        return self


class AppealCreate(BaseModel):
    reason: str = Field(min_length=10, max_length=4000)
    desired_resolution: str = Field(min_length=4, max_length=2000)


class AppealReview(BaseModel):
    decision: Literal["approved", "rejected"]
    review_comment: str = Field(min_length=4, max_length=2000)
    reprocess_instructions: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_instructions(self):
        if self.decision == "approved" and not (self.reprocess_instructions or "").strip():
            raise ValueError("审核通过时必须填写重新办理要求")
        return self


class PhoneFollowUpCreate(BaseModel):
    ticket_version: int = Field(ge=1)
    contact_result: Literal["reached", "no_answer", "wrong_number"]
    satisfaction: Optional[Literal["satisfied", "mostly_satisfied", "dissatisfied"]] = None
    outcome: Literal["confirmed", "needs_followup", "appeal_requested"]
    notes: str = Field(min_length=4, max_length=4000)

    @model_validator(mode="after")
    def validate_follow_up(self):
        if self.contact_result != "reached" and self.outcome != "needs_followup":
            raise ValueError("未接通或号码有误时只能选择继续回访")
        if self.outcome == "confirmed" and self.satisfaction not in {"satisfied", "mostly_satisfied"}:
            raise ValueError("确认办结时回访评价必须为满意或基本满意")
        return self

class TicketStatusUpdate(BaseModel):
    status: str = Field(min_length=2, max_length=32)
    remark: Optional[str] = Field(default=None, max_length=2000)
    version: Optional[int] = Field(default=None, ge=1)


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: str
    request_type: str
    description: str
    location: str
    event: Optional[str]
    occurred_at_text: Optional[str]
    occurred_at_start: Optional[datetime]
    occurred_at_end: Optional[datetime]
    occurred_at_precision: Optional[str]
    timezone: str
    target: Optional[str]
    contact: Optional[str] = None
    category_id: Optional[int] = None
    category_code: Optional[str] = None
    category_name: Optional[str] = None
    category_path: Optional[str] = None
    requested_priority: Optional[str] = None
    priority: str
    priority_confirmed_at: Optional[datetime] = None
    status: str
    status_label: Optional[str] = None
    department_name: Optional[str] = None
    assigned_department_id: Optional[int] = None
    assigned_user_id: Optional[int] = None
    creator_name: Optional[str] = None
    assignee_name: Optional[str] = None
    source: str
    version: int
    accepted_at: Optional[datetime]
    resolved_at: Optional[datetime]
    closed_at: Optional[datetime]
    accept_due_at: Optional[datetime] = None
    resolve_due_at: Optional[datetime] = None
    remaining_seconds: Optional[int] = None
    is_overdue: bool = False
    sla_state: str = "on_track"
    sla_paused_at: Optional[datetime] = None
    sla_pause_reason: Optional[str] = None
    total_paused_seconds: int = 0
    reminder_count: int = 0
    resolution_summary: Optional[str] = None
    resolution_measures: Optional[str] = None
    resolution_outcome: Optional[str] = None
    public_reply: Optional[str] = None
    internal_note: Optional[str] = None
    rejection_reason_code: Optional[str] = None
    rejection_detail: Optional[str] = None
    suggested_channel: Optional[str] = None
    needs_supplement: bool = False
    collaboration_status: str = "none"
    supplement_reason: Optional[str] = None
    supplement_requested_at: Optional[datetime] = None
    supplemented_at: Optional[datetime] = None
    dispatch_return_reason: Optional[str] = None
    dispute_reason: Optional[str] = None
    dispute_resolution: Optional[str] = None
    closure_type: Optional[str] = None
    handling_round: int = 1
    appeal_count: int = 0
    external_platform: Optional[str] = None
    external_ticket_id: Optional[str] = None
    external_sync_status: Optional[str] = None
    external_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TicketStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    operation_type: str
    content: Optional[str]
    previous_status: Optional[str]
    current_status: str
    remark: Optional[str]
    created_at: datetime


class TicketFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resolution_version: int
    rating: str
    comment: Optional[str]
    result: str
    created_at: datetime


class WorkOrderHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: str
    previous_status: Optional[str]
    current_status: str
    content: str
    created_at: datetime


class WorkOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_order_no: str
    ticket_id: str
    task_type: str
    status: str
    department_id: int
    department_name: Optional[str] = None
    assignee_user_id: Optional[int]
    assignee_name: Optional[str] = None
    instructions: str
    result_summary: Optional[str]
    result_measures: Optional[str]
    result_outcome: Optional[str]
    public_content: Optional[str]
    internal_note: Optional[str]
    return_reason: Optional[str]
    source_work_order_id: Optional[str]
    accepted_at: Optional[datetime]
    submitted_at: Optional[datetime]
    completed_at: Optional[datetime]
    version: int
    created_at: datetime
    updated_at: datetime
    history: list[WorkOrderHistoryRead] = Field(default_factory=list)


class TicketDetail(TicketRead):
    history: list[TicketStatusHistoryRead] = Field(default_factory=list)
    feedbacks: list[TicketFeedbackRead] = Field(default_factory=list)
    work_orders: list[WorkOrderRead] = Field(default_factory=list)


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ticket_id: str
    uploader_user_id: Optional[int]
    uploader_role: str
    attachment_type: str
    visibility: Literal["public", "internal"]
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    scan_status: str
    scan_engine: Optional[str]
    scanned_at: Optional[datetime]
    created_at: datetime


class AttachmentList(BaseModel):
    items: list[AttachmentRead]
    total: int


class AttachmentDelete(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class TicketCreated(BaseModel):
    ticket: TicketRead
    idempotent_replay: bool


class TicketList(BaseModel):
    items: list[TicketRead]
    page: int
    page_size: int
    total: int


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ticket_id: Optional[str]
    event_type: str
    channel: str
    title: str
    content: str
    status: str
    delivery_status: str
    read_at: Optional[datetime]
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationRead]
    page: int
    page_size: int
    total: int
    unread_count: int


class NotificationChannelRead(BaseModel):
    channel: str
    label: str
    enabled: bool
    phase: str


class PhoneFollowUpRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    task_id: str
    ticket_id: str
    caller_user_id: Optional[int]
    caller_name: Optional[str] = None
    contact_result: str
    satisfaction: Optional[str]
    outcome: str
    notes: str
    created_at: datetime


class FollowUpTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ticket_id: str
    handling_round: int
    status: str
    assigned_user_id: Optional[int]
    assignee_name: Optional[str] = None
    due_at: datetime
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    records: list[PhoneFollowUpRecordRead] = Field(default_factory=list)


class FollowUpTaskList(BaseModel):
    items: list[FollowUpTaskRead]
    page: int
    page_size: int
    total: int


class AppealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    appeal_no: str
    ticket_id: str
    citizen_user_id: Optional[int]
    citizen_name: Optional[str] = None
    sequence: int
    status: str
    reason: str
    desired_resolution: str
    review_comment: Optional[str]
    reviewed_by_user_id: Optional[int]
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime]
    reprocess_instructions: Optional[str]
    result_summary: Optional[str]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class AppealList(BaseModel):
    items: list[AppealRead]
    page: int
    page_size: int
    total: int


class TicketQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    status: Optional[str] = None
    request_type: Optional[str] = None
    department_id: Optional[int] = Field(default=None, gt=0)
    category_id: Optional[int] = Field(default=None, gt=0)
    priority: Optional[str] = None
    sla_state: Optional[Literal["on_track", "due_soon", "overdue", "paused"]] = None
    created_from: Optional[datetime] = None
    created_to: Optional[datetime] = None
    keyword: Optional[str] = Field(default=None, max_length=100)
    mine: bool = False
    my_department: bool = False
    sort: Literal["created_at", "updated_at", "priority"] = "created_at"
    order: Literal["asc", "desc"] = "desc"

    @field_validator("status")
    @classmethod
    def validate_status_filter(cls, value):
        if value is not None and value not in STATUSES:
            raise ValueError("status 筛选值无效")
        return value

    @field_validator("request_type")
    @classmethod
    def validate_type_filter(cls, value):
        if value is not None and value not in REQUEST_TYPES:
            raise ValueError("request_type 筛选值无效")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority_filter(cls, value):
        if value is not None and value not in PRIORITIES:
            raise ValueError("priority 筛选值无效")
        return value

    @model_validator(mode="after")
    def validate_created_range(self):
        for value in (self.created_from, self.created_to):
            if value is not None and value.utcoffset() is None:
                raise ValueError("创建时间筛选必须包含时区")
        if self.created_from and self.created_to and self.created_from >= self.created_to:
            raise ValueError("created_to 必须晚于 created_from")
        return self


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class AiAnalyzeRequest(BaseModel):
    suggestion_types: list[Literal[
        "assignment", "similarity", "summary", "completeness", "document_draft", "risk",
        "triage_assistant", "handling_assistant",
    ]] = Field(
        default_factory=lambda: ["triage_assistant"],
        min_length=1,
        max_length=8,
    )
    capability: Optional[Literal["triage_assistant", "handling_assistant"]] = None


class AiReviewRequest(BaseModel):
    decision: Literal[
        "helpful", "not_helpful",
        "adopted", "adopted_with_edits", "rejected",
    ]
    comment: Optional[str] = Field(default=None, max_length=1000)
    edited_content: Optional[dict] = None


class PreReviewRequest(BaseModel):
    description: str = Field(min_length=4, max_length=5000)
    request_type: Optional[str] = Field(default=None, max_length=16)
    location: Optional[str] = Field(default=None, max_length=500)
    occurred_at_text: Optional[str] = Field(default=None, max_length=200)
    target: Optional[str] = Field(default=None, max_length=500)
    contact: Optional[str] = Field(default=None, max_length=200)


class PreReviewResult(BaseModel):
    identified_type: str
    identified_location: str
    identified_time: str
    identified_target: str
    impact: str
    urgency_hint: str
    missing_fields: list[str]
    field_tips: dict[str, str]
    normalized_description: str
    recommended_department: Optional[str] = None
    department_reason: Optional[str] = None
    provider: str
    advisory_only: Literal[True] = True


class AiSuggestionRead(BaseModel):
    id: str
    ticket_id: str
    suggestion_type: str
    status: str
    risk_level: str
    confidence: int
    provider: str
    model_name: str
    result: dict
    explanation: Optional[str]
    review_decision: Optional[str]
    review_comment: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime
    advisory_only: Literal[True] = True


class HotspotRead(BaseModel):
    cluster_key: str
    label: str
    count: int
    urgent_count: int
    sample_ticket_ids: list[str]


class IntegrationStatusRead(BaseModel):
    integration_type: str
    enabled: bool
    configured: bool
    mode: str
    message: str


class TicketSyncRequest(BaseModel):
    force: bool = False


class SmsDispatchRequest(BaseModel):
    phone: str = Field(pattern=r"^1\d{10}$")
    template_code: str = Field(min_length=2, max_length=100)
    parameters: dict[str, str] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value):
        if len(value) > 20 or any(len(str(key)) > 64 or len(str(item)) > 500 for key, item in value.items()):
            raise ValueError("短信模板参数超过限制")
        return value


class OidcExchangeRequest(BaseModel):
    code: str = Field(min_length=4, max_length=4096)
    redirect_uri: str = Field(min_length=8, max_length=2048)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: str
    department_id: Optional[int]
    is_active: bool


class UserList(BaseModel):
    items: list[UserRead]
    page: int
    page_size: int
    total: int


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)
    role: str
    department_id: Optional[int] = Field(default=None, gt=0)
    is_active: bool = True

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        if value not in ROLES:
            raise ValueError("role 无效")
        return value


class UserUpdate(BaseModel):
    password: Optional[str] = Field(default=None, min_length=12, max_length=256)
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    role: Optional[str] = None
    department_id: Optional[int] = Field(default=None, gt=0)
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        if value is not None and value not in ROLES:
            raise ValueError("role 无效")
        return value


class DepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: Optional[str]
    is_active: bool


class DepartmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = None


class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    parent_id: Optional[int]
    level: int
    default_department_id: Optional[int]
    default_department_name: Optional[str] = None
    accept_sla_minutes: int
    resolve_sla_minutes: int
    is_active: bool


class CategoryCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=2, max_length=100)
    parent_id: Optional[int] = Field(default=None, gt=0)
    default_department_id: Optional[int] = Field(default=None, gt=0)
    accept_sla_minutes: int = Field(default=120, ge=1, le=525600)
    resolve_sla_minutes: int = Field(default=4320, ge=1, le=525600)


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    parent_id: Optional[int] = Field(default=None, gt=0)
    default_department_id: Optional[int] = Field(default=None, gt=0)
    accept_sla_minutes: Optional[int] = Field(default=None, ge=1, le=525600)
    resolve_sla_minutes: Optional[int] = Field(default=None, ge=1, le=525600)
    is_active: Optional[bool] = None


class DashboardMetric(BaseModel):
    key: str
    label: str
    value: float
    unit: Optional[str] = None


class DashboardSlice(BaseModel):
    name: str
    value: int


class DepartmentSlaStat(BaseModel):
    department_name: str
    total: int
    overdue: int
    overdue_rate: float


class DashboardData(BaseModel):
    metrics: list[DashboardMetric]
    status_distribution: list[DashboardSlice]
    request_type_distribution: list[DashboardSlice]
    department_distribution: list[DashboardSlice]
    department_sla: list[DepartmentSlaStat] = Field(default_factory=list)
    recent_tickets: list[TicketRead]


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_user_id: Optional[int]
    actor_type: str
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    outcome: str
    details: Optional[str]
    request_id: Optional[str]
    created_at: datetime


class AuditLogList(BaseModel):
    items: list[AuditLogRead]
    page: int
    page_size: int
    total: int


class SuccessResponse(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T


class ErrorBody(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorBody
