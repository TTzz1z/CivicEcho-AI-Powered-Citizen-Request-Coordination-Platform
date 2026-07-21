from app.models import (
    AuditLogModel,
    CategoryModel,
    DepartmentModel,
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

    assert "ix_audit_request_id" in audit_indexes
    assert "ix_tickets_external_reference" in ticket_indexes
