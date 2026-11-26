from app.models import (
    AuditLogModel,
    CategoryModel,
    DepartmentModel,
    KbChunkModel,
    NotificationModel,
    TicketFeedbackModel,
    TicketModel,
    TicketStatusHistoryModel,
    UserModel,
    WorkOrderHistoryModel,
)


def test_identity_primary_keys_match_the_migration_schema():
    models = (
        AuditLogModel,
        CategoryModel,
        DepartmentModel,
        TicketFeedbackModel,
        TicketModel,
        TicketStatusHistoryModel,
        UserModel,
        WorkOrderHistoryModel,
    )

    assert all(model.__table__.c.id.identity is not None for model in models)


def test_migrated_indexes_remain_declared_in_orm_metadata():
    audit_indexes = {index.name for index in AuditLogModel.__table__.indexes}
    ticket_indexes = {index.name for index in TicketModel.__table__.indexes}
    notification_indexes = {index.name for index in NotificationModel.__table__.indexes}
    kb_chunk_indexes = {index.name for index in KbChunkModel.__table__.indexes}

    assert "ix_audit_request_id" in audit_indexes
    assert {
        "ix_tickets_external_reference",
        "ix_tickets_dept_status_created",
        "ix_tickets_assignee_status_created",
        "ix_tickets_status_updated",
        "ix_tickets_collab_status_created",
        "ix_tickets_status_paused_resolve_due",
    } <= ticket_indexes
    assert "ix_notifications_recipient_created_id" in notification_indexes
    assert {
        "ix_kb_chunks_embedding_hnsw",
        "ix_kb_chunks_content_trgm",
    } <= kb_chunk_indexes
