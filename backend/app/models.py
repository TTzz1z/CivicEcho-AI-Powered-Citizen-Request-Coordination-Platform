from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Identity, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class DepartmentModel(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    department_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("departments.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    oidc_subject: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    directory_external_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    department: Mapped[Optional[DepartmentModel]] = relationship()

    __table_args__ = (Index("ix_users_department_role", "department_id", "role"),)


class CategoryModel(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("categories.id", ondelete="RESTRICT"))
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    default_department_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("departments.id", ondelete="SET NULL"))
    accept_sla_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    resolve_sla_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=4320)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    parent: Mapped[Optional["CategoryModel"]] = relationship(remote_side=[id])
    default_department: Mapped[Optional[DepartmentModel]] = relationship()

    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_categories_parent_name"),
        Index("ix_categories_parent_active", "parent_id", "is_active"),
    )


class TicketModel(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_type: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(String(500), nullable=False)
    event: Mapped[Optional[str]] = mapped_column(Text)
    occurred_at: Mapped[Optional[str]] = mapped_column(String(200))  # 0001 compatibility column
    occurred_at_text: Mapped[Optional[str]] = mapped_column(String(200))
    occurred_at_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    occurred_at_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    occurred_at_precision: Mapped[Optional[str]] = mapped_column(String(32))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    target: Mapped[Optional[str]] = mapped_column(String(500))
    contact: Mapped[Optional[str]] = mapped_column(String(200))
    creator_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    anonymous_creator_key: Mapped[Optional[str]] = mapped_column(String(64))
    assigned_department_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("departments.id", ondelete="SET NULL"))
    assigned_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    category_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("categories.id", ondelete="SET NULL"))
    requested_priority: Mapped[Optional[str]] = mapped_column(String(16))
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    priority_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    priority_confirmed_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="rasa")
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    accept_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolve_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sla_paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sla_pause_reason: Mapped[Optional[str]] = mapped_column(String(500))
    total_paused_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolution_summary: Mapped[Optional[str]] = mapped_column(String(500))
    resolution_measures: Mapped[Optional[str]] = mapped_column(Text)
    resolution_outcome: Mapped[Optional[str]] = mapped_column(String(32))
    public_reply: Mapped[Optional[str]] = mapped_column(Text)
    internal_note: Mapped[Optional[str]] = mapped_column(Text)
    rejection_reason_code: Mapped[Optional[str]] = mapped_column(String(64))
    rejection_detail: Mapped[Optional[str]] = mapped_column(Text)
    suggested_channel: Mapped[Optional[str]] = mapped_column(String(500))
    needs_supplement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collaboration_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    supplement_reason: Mapped[Optional[str]] = mapped_column(Text)
    supplement_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    supplemented_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispatch_return_reason: Mapped[Optional[str]] = mapped_column(Text)
    dispute_reason: Mapped[Optional[str]] = mapped_column(Text)
    dispute_resolution: Mapped[Optional[str]] = mapped_column(Text)
    closure_type: Mapped[Optional[str]] = mapped_column(String(32))
    handling_round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    appeal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    external_platform: Mapped[Optional[str]] = mapped_column(String(32))
    external_ticket_id: Mapped[Optional[str]] = mapped_column(String(128))
    external_sync_status: Mapped[Optional[str]] = mapped_column(String(24))
    external_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    history: Mapped[list["TicketStatusHistoryModel"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    feedbacks: Mapped[list["TicketFeedbackModel"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    attachments: Mapped[list["TicketAttachmentModel"]] = relationship(back_populates="ticket")
    work_orders: Mapped[list["WorkOrderModel"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    notifications: Mapped[list["NotificationModel"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    follow_up_tasks: Mapped[list["FollowUpTaskModel"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    appeals: Mapped[list["AppealModel"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    ai_suggestions: Mapped[list["AiSuggestionModel"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    department: Mapped[Optional[DepartmentModel]] = relationship(foreign_keys=[assigned_department_id])
    creator: Mapped[Optional[UserModel]] = relationship(foreign_keys=[creator_user_id])
    assignee: Mapped[Optional[UserModel]] = relationship(foreign_keys=[assigned_user_id])
    category: Mapped[Optional[CategoryModel]] = relationship(foreign_keys=[category_id])

    __table_args__ = (
        Index("ix_tickets_created_at", "created_at"),
        Index("ix_tickets_contact_created_at", "contact", "created_at"),
        Index("ix_tickets_status_created", "status", "created_at"),
        Index("ix_tickets_department_status", "assigned_department_id", "status"),
        Index("ix_tickets_creator_created", "creator_user_id", "created_at"),
        Index("ix_tickets_anonymous_creator", "anonymous_creator_key"),
        Index("ix_tickets_category_status", "category_id", "status"),
        Index("ix_tickets_accept_due", "accept_due_at"),
        Index("ix_tickets_resolve_due", "resolve_due_at"),
        Index("ix_tickets_external_reference", "external_platform", "external_ticket_id", unique=True),
    )


class WorkOrderModel(Base):
    """A department-owned handling task under a citizen request master ticket."""

    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    work_order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    department_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False)
    assignee_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    result_summary: Mapped[Optional[str]] = mapped_column(String(500))
    result_measures: Mapped[Optional[str]] = mapped_column(Text)
    result_outcome: Mapped[Optional[str]] = mapped_column(String(32))
    public_content: Mapped[Optional[str]] = mapped_column(Text)
    internal_note: Mapped[Optional[str]] = mapped_column(Text)
    return_reason: Mapped[Optional[str]] = mapped_column(Text)
    source_work_order_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("work_orders.id", ondelete="SET NULL"))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    ticket: Mapped[TicketModel] = relationship(back_populates="work_orders")
    department: Mapped[DepartmentModel] = relationship(foreign_keys=[department_id])
    assignee: Mapped[Optional[UserModel]] = relationship(foreign_keys=[assignee_user_id])
    history: Mapped[list["WorkOrderHistoryModel"]] = relationship(back_populates="work_order", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_work_orders_ticket_status", "ticket_id", "status"),
        Index("ix_work_orders_department_status", "department_id", "status"),
        Index("ix_work_orders_assignee_status", "assignee_user_id", "status"),
    )


class WorkOrderHistoryModel(Base):
    __tablename__ = "work_order_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    work_order_id: Mapped[str] = mapped_column(String(36), ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False)
    operator_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[Optional[str]] = mapped_column(String(24))
    current_status: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    work_order: Mapped[WorkOrderModel] = relationship(back_populates="history")

    __table_args__ = (Index("ix_work_order_history_order_created", "work_order_id", "created_at"),)


class TicketStatusHistoryModel(Base):
    __tablename__ = "ticket_status_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False)
    operator_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="status_change")
    content: Mapped[Optional[str]] = mapped_column(Text)
    previous_status: Mapped[Optional[str]] = mapped_column(String(32))
    current_status: Mapped[str] = mapped_column(String(32), nullable=False)
    remark: Mapped[Optional[str]] = mapped_column(Text)  # compatibility alias persisted for 0001 clients
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ticket: Mapped[TicketModel] = relationship(back_populates="history")

    __table_args__ = (Index("ix_ticket_history_ticket_created", "ticket_id", "created_at"),)


class TicketFeedbackModel(Base):
    __tablename__ = "ticket_feedbacks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False)
    citizen_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    resolution_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ticket: Mapped[TicketModel] = relationship(back_populates="feedbacks")

    __table_args__ = (
        UniqueConstraint("ticket_id", "resolution_version", name="uq_ticket_feedback_resolution"),
        Index("ix_ticket_feedback_ticket_created", "ticket_id", "created_at"),
    )


class TicketAttachmentModel(Base):
    __tablename__ = "ticket_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False)
    uploader_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    uploader_role: Mapped[str] = mapped_column(String(32), nullable=False)
    uploader_department_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("departments.id", ondelete="SET NULL"))
    attachment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="s3")
    storage_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    scan_status: Mapped[str] = mapped_column(String(16), nullable=False)
    scan_engine: Mapped[Optional[str]] = mapped_column(String(64))
    scan_detail: Mapped[Optional[str]] = mapped_column(String(500))
    scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    delete_reason: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ticket: Mapped[TicketModel] = relationship(back_populates="attachments")

    __table_args__ = (
        Index("ix_ticket_attachments_ticket_created", "ticket_id", "created_at"),
        Index("ix_ticket_attachments_uploader", "uploader_user_id", "created_at"),
        Index("ix_ticket_attachments_scan_status", "scan_status"),
    )


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64))
    resource_id: Mapped[Optional[str]] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text)
    request_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_audit_action_created", "action", "created_at"),
        Index("ix_audit_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_request_id", "request_id"),
    )


class NotificationModel(Base):
    """A recipient-scoped notification. Channel values reserve future delivery adapters."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ticket_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="in_app")
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unread")
    delivery_status: Mapped[str] = mapped_column(String(16), nullable=False, default="delivered")
    event_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    recipient: Mapped[UserModel] = relationship(foreign_keys=[recipient_user_id])
    ticket: Mapped[Optional[TicketModel]] = relationship(back_populates="notifications")

    __table_args__ = (
        Index("ix_notifications_recipient_status_created", "recipient_user_id", "status", "created_at"),
        Index("ix_notifications_ticket_created", "ticket_id", "created_at"),
    )


class FollowUpTaskModel(Base):
    __tablename__ = "follow_up_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False)
    handling_round: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    assigned_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    ticket: Mapped[TicketModel] = relationship(back_populates="follow_up_tasks")
    assignee: Mapped[Optional[UserModel]] = relationship(foreign_keys=[assigned_user_id])
    records: Mapped[list["PhoneFollowUpRecordModel"]] = relationship(back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("ticket_id", "handling_round", name="uq_follow_up_ticket_round"),
        Index("ix_follow_up_tasks_status_due", "status", "due_at"),
        Index("ix_follow_up_tasks_assignee_status", "assigned_user_id", "status"),
    )


class PhoneFollowUpRecordModel(Base):
    __tablename__ = "phone_follow_up_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("follow_up_tasks.id", ondelete="CASCADE"), nullable=False)
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False)
    caller_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    contact_result: Mapped[str] = mapped_column(String(24), nullable=False)
    satisfaction: Mapped[Optional[str]] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    task: Mapped[FollowUpTaskModel] = relationship(back_populates="records")
    caller: Mapped[Optional[UserModel]] = relationship(foreign_keys=[caller_user_id])

    __table_args__ = (Index("ix_phone_follow_up_ticket_created", "ticket_id", "created_at"),)


class AppealModel(Base):
    __tablename__ = "appeals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    appeal_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False)
    citizen_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="submitted")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    desired_resolution: Mapped[str] = mapped_column(Text, nullable=False)
    review_comment: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reprocess_instructions: Mapped[Optional[str]] = mapped_column(Text)
    result_summary: Mapped[Optional[str]] = mapped_column(Text)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    ticket: Mapped[TicketModel] = relationship(back_populates="appeals")
    citizen: Mapped[Optional[UserModel]] = relationship(foreign_keys=[citizen_user_id])
    reviewer: Mapped[Optional[UserModel]] = relationship(foreign_keys=[reviewed_by_user_id])

    __table_args__ = (
        UniqueConstraint("ticket_id", "sequence", name="uq_appeal_ticket_sequence"),
        Index("ix_appeals_status_created", "status", "created_at"),
        Index("ix_appeals_ticket_created", "ticket_id", "created_at"),
    )


class AiSuggestionModel(Base):
    """Immutable AI output plus an explicit human review; never changes ticket state."""

    __tablename__ = "ai_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False)
    suggestion_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="rules")
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="phase6-rules-v1")
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    generated_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    review_decision: Mapped[Optional[str]] = mapped_column(String(24))
    review_comment: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    ticket: Mapped[TicketModel] = relationship(back_populates="ai_suggestions")

    __table_args__ = (
        UniqueConstraint("ticket_id", "suggestion_type", "input_fingerprint", name="uq_ai_suggestion_input"),
        Index("ix_ai_suggestions_ticket_created", "ticket_id", "created_at"),
        Index("ix_ai_suggestions_type_risk_created", "suggestion_type", "risk_level", "created_at"),
    )


class IntegrationEventModel(Base):
    """Metadata-only integration ledger. Payloads and credentials are deliberately not persisted."""

    __tablename__ = "integration_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    integration_type: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64))
    resource_id: Mapped[Optional[str]] = mapped_column(String(128))
    external_id: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_hash: Mapped[Optional[str]] = mapped_column(String(64))
    response_code: Mapped[Optional[int]] = mapped_column(Integer)
    error_summary: Mapped[Optional[str]] = mapped_column(String(500))
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    request_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_integration_events_type_created", "integration_type", "created_at"),
        Index("ix_integration_events_resource", "resource_type", "resource_id", "created_at"),
    )


class NotificationOutboxModel(Base):
    """Reliable outbox for async notification delivery with retry."""

    __tablename__ = "notification_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    recipient_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ticket_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("tickets.ticket_id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="in_app")
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        Index("ix_outbox_status_next_retry", "status", "next_retry_at"),
        Index("ix_outbox_recipient_created", "recipient_user_id", "created_at"),
    )


class LoginAttemptModel(Base):
    """Database-backed login rate limiting for shared state across workers."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_login_attempts_key_time", "key", "attempted_at"),
    )


# --- Knowledge Base Models ---

class KbDocumentModel(Base):
    """Knowledge base document with lifecycle management."""
    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_number: Mapped[Optional[str]] = mapped_column(String(200))  # 文号
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(200))  # 发布单位
    department_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("departments.id", ondelete="SET NULL"))
    kb_type: Mapped[str] = mapped_column(String(64), nullable=False, default="policy")  # policy/guide/faq/internal/procedure/case
    domain: Mapped[Optional[str]] = mapped_column(String(200))  # 政策领域
    region: Mapped[Optional[str]] = mapped_column(String(200))  # 适用地区
    audience: Mapped[Optional[str]] = mapped_column(String(200))  # 适用人群
    file_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")  # pdf/word/markdown/text
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="PUBLIC")  # PUBLIC/DEPARTMENT/INTERNAL
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")  # DRAFT/REVIEWING/PUBLISHED/REJECTED/WITHDRAWN/EXPIRED/PARSE_FAILED
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_version_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("kb_documents.id", ondelete="SET NULL"))
    replaces_doc_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("kb_documents.id", ondelete="SET NULL"))
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    keywords: Mapped[Optional[str]] = mapped_column(Text)  # comma-separated
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending/parsing/done/failed
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    published_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    review_comment: Mapped[Optional[str]] = mapped_column(Text)
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_content: Mapped[Optional[str]] = mapped_column(Text)  # extracted text
    # File metadata
    storage_key: Mapped[Optional[str]] = mapped_column(String(500))
    original_filename: Mapped[Optional[str]] = mapped_column(String(500))
    mime_type: Mapped[Optional[str]] = mapped_column(String(200))
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    ocr_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")  # none/required/done/failed
    ocr_quality: Mapped[Optional[float]] = mapped_column(Float)
    # Tags & metadata
    tags: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    meta_json: Mapped[Optional[str]] = mapped_column(Text)
    # Index & embedding
    index_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending/building/ready/failed
    embedding_model: Mapped[Optional[str]] = mapped_column(String(128))
    chunking_version: Mapped[Optional[str]] = mapped_column(String(32), default="v1")
    # Live retrieval batch. Rebuild writes a new batch first; switch only on full success.
    active_index_batch: Mapped[Optional[str]] = mapped_column(String(64))
    published_department_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("departments.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    department: Mapped[Optional[DepartmentModel]] = relationship(foreign_keys=[department_id])
    published_department: Mapped[Optional[DepartmentModel]] = relationship(foreign_keys=[published_department_id])
    chunks: Mapped[list["KbChunkModel"]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_kb_docs_status_visibility", "status", "visibility"),
        Index("ix_kb_docs_dept_status", "department_id", "status"),
        Index("ix_kb_docs_type_domain", "kb_type", "domain"),
        Index("ix_kb_docs_kb_type_status", "kb_type", "status"),
        Index("ix_kb_docs_index_status", "index_status"),
        Index("ix_kb_docs_replaces", "replaces_doc_id"),
        Index("ix_kb_docs_published_dept", "published_department_id"),
        Index("ix_kb_docs_active_index_batch", "active_index_batch"),
    )


class KbChunkModel(Base):
    """Document chunk for retrieval."""
    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # pgvector column; ORM uses pgvector.sqlalchemy.Vector so INSERT/SELECT type-correctly.
    # Raw-SQL writes in kb_service._store_embedding remain valid (cast as ::vector).
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1024))
    chunk_hash: Mapped[Optional[str]] = mapped_column(String(64))
    keywords: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # P0-D chunk-level embedding metadata for traceability.
    embedding_model: Mapped[Optional[str]] = mapped_column(String(128))
    embedding_provider: Mapped[Optional[str]] = mapped_column(String(64))
    embedding_dimension: Mapped[Optional[int]] = mapped_column(Integer)
    embedding_fallback: Mapped[str] = mapped_column(String(32), nullable=False, default="none")  # none/fallback_used/primary_failed
    # Staging vs live: only chunks matching document.active_index_batch are searchable.
    index_batch_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document: Mapped[KbDocumentModel] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_kb_chunks_doc_idx", "document_id", "chunk_index"),
        Index("ix_kb_chunks_doc_idx_hash", "document_id", "chunk_hash"),
        Index("ix_kb_chunks_doc_batch", "document_id", "index_batch_id"),
    )


class KbFeedbackModel(Base):
    """User feedback on RAG answers."""
    __tablename__ = "kb_feedback"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[Optional[str]] = mapped_column(Text)
    document_ids: Mapped[Optional[str]] = mapped_column(String(500))  # comma-separated doc IDs
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)  # helpful/inaccurate/outdated/no_answer
    comment: Mapped[Optional[str]] = mapped_column(Text)
    route: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_kb_feedback_type_time", "feedback_type", "created_at"),
    )


class KbEvalCaseModel(Base):
    """RAG evaluation case."""
    __tablename__ = "kb_eval_cases"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(String(200))
    scenario: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer_summary: Mapped[Optional[str]] = mapped_column(Text)
    expected_doc_ids: Mapped[Optional[str]] = mapped_column(String(500))
    must_cite_doc_ids: Mapped[Optional[str]] = mapped_column(String(500))
    must_not_cite_doc_ids: Mapped[Optional[str]] = mapped_column(String(500))
    must_avoid_keywords: Mapped[Optional[str]] = mapped_column(Text)
    expected_role: Mapped[str] = mapped_column(String(32), default="citizen")
    expected_no_answer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_kb_eval_cases_scenario", "scenario", "is_active"),
    )


class KbEvalRunModel(Base):
    """Single execution of an evaluation case."""
    __tablename__ = "kb_eval_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kb_eval_cases.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[Optional[str]] = mapped_column(Text)
    citations_json: Mapped[Optional[str]] = mapped_column(Text)
    no_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retrieval_hit: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    citation_correct: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    answer_faithful: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    expired_policy_blocked: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    permission_isolated: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    provider: Mapped[Optional[str]] = mapped_column(String(64))
    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    evaluator: Mapped[str] = mapped_column(String(64), default="rules")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_kb_eval_runs_case", "case_id", "created_at"),
    )


class KbNoAnswerQuestionModel(Base):
    """User query that produced no evidence; tracked for improvement."""
    __tablename__ = "kb_no_answer_questions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    role: Mapped[Optional[str]] = mapped_column(String(32))
    route: Mapped[Optional[str]] = mapped_column(String(64))
    retrieved_doc_ids: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")  # open/assigned/resolved/wont_fix
    assigned_department_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("departments.id", ondelete="SET NULL"))
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_kb_no_answer_status", "status", "created_at"),
    )


class AiUsageLogModel(Base):
    """Audit log for every model (rules / embedding / LLM) invocation.

    One row per call. Drives the admin "AI 用量与安全" page.

    Round 2 additions (migration 0017):
    - session_id: per-session identifier (replaces shared user:default fallback)
    - capability: which AI capability produced this call
      (orchestrator_classify|ticket_draft|policy_rag|service_guide|ticket_advice|
       ai_analyze|pre_review|embedding_index|embedding_query|semantic_cache)
    - provider: model provider label
    - total_tokens: prompt + completion tokens
    - usage_unavailable: True when the model response did not include a usage
      block. MUST NOT be silently treated as 0.
    - degrade_reason: stable reason code for degraded paths
    - budget_exceeded: separate from `degraded` for clearer reporting
    - error_code: stable error code (HTTP status / exception class)
    - text_count / text_chars: embedding batch size metadata
    """
    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    role: Mapped[Optional[str]] = mapped_column(String(32))
    route: Mapped[Optional[str]] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_tier: Mapped[str] = mapped_column(String(32), nullable=False)  # rules|embedding|llm_lite|llm_full
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rate_limited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    estimated_cost_rmb: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Round 2 fields (all nullable / safe defaults for backwards compatibility)
    session_id: Mapped[Optional[str]] = mapped_column(String(128))
    capability: Mapped[Optional[str]] = mapped_column(String(64))
    provider: Mapped[Optional[str]] = mapped_column(String(64))
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_unavailable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    degrade_reason: Mapped[Optional[str]] = mapped_column(String(64))
    budget_exceeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    text_count: Mapped[Optional[int]] = mapped_column(Integer)
    text_chars: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_ai_usage_logs_created_at", "created_at"),
        Index("ix_ai_usage_logs_user_created", "user_id", "created_at"),
        Index("ix_ai_usage_logs_route_created", "route", "created_at"),
        Index("ix_ai_usage_logs_role_created", "role", "created_at"),
        Index("ix_ai_usage_logs_tier_created", "model_tier", "created_at"),
        Index("ix_ai_usage_logs_session_created", "session_id", "created_at"),
        Index("ix_ai_usage_logs_capability_created", "capability", "created_at"),
        Index("ix_ai_usage_logs_provider_created", "provider", "created_at"),
    )


class AiUsageBudgetModel(Base):
    """Daily LLM call budget per user (override). Platform budget is in settings."""
    __tablename__ = "ai_usage_budgets"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    role: Mapped[Optional[str]] = mapped_column(String(32))
    daily_llm_call_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    daily_token_limit: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_ai_usage_budgets_role", "role"),
    )
