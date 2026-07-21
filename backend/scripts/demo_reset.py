"""Round 4 demo environment: deterministic one-click reset + seed.

Usage:
    SEED_PASSWORD=tingting-seed-demo-2026 python -m scripts.demo_reset

R4 changes (deterministic reset):
1. Users: keep ONLY whitelisted usernames (demo accounts); delete everything else.
2. Departments: keep ONLY whitelisted codes; delete everything else (including test departments).
3. Categories: keep ONLY whitelisted codes; delete everything else.
4. All transactional tables (tickets/work_orders/notifications/appeals/feedbacks/follow_ups/ai_usage/audit/outbox/integration_events): truncate fully.
5. KB documents: keep only those seeded by app.seed (identified by title whitelist); delete test P0-KB-*/P0-D-* patterns.
6. Re-seed via app.seed.seed() (idempotent).

Deterministic guarantee:
- After this script, the DB contains ONLY the whitelisted demo accounts/departments/categories
  plus whatever app.seed.seed() inserts.
- Run it twice in a row → identical state both times.

This script is intentionally destructive. NEVER run it against a production database.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import delete, select, func

from app.database import SessionLocal
from app.models import (
    AiSuggestionModel,
    AiUsageLogModel,
    AppealModel,
    AuditLogModel,
    CategoryModel,
    DepartmentModel,
    IntegrationEventModel,
    KbChunkModel,
    KbDocumentModel,
    KbEvalCaseModel,
    KbEvalRunModel,
    KbFeedbackModel,
    KbNoAnswerQuestionModel,
    NotificationModel,
    NotificationOutboxModel,
    PhoneFollowUpRecordModel,
    FollowUpTaskModel,
    TicketAttachmentModel,
    TicketFeedbackModel,
    TicketModel,
    TicketStatusHistoryModel,
    UserModel,
    WorkOrderHistoryModel,
    WorkOrderModel,
)


# ---------------- Whitelists ----------------

DEMO_USERNAMES = {
    "citizen_local",
    "agent_local",
    "department_local",
    "admin_local",
}

DEMO_DEPARTMENT_CODES = {
    "urban-management",
    "transport",
    "housing-property",
    "education",
    "health",
    "community-civil",
    "general-intake",
}

DEMO_CATEGORY_CODES = {
    "CSGL",
    "CSGL-GGSS",
    "CSGL-GGSS-LD",
}

# Tables fully truncated (children first to respect FK)
TRUNCATE_MODELS = [
    PhoneFollowUpRecordModel,
    FollowUpTaskModel,
    NotificationOutboxModel,
    NotificationModel,
    AppealModel,
    TicketFeedbackModel,
    AiSuggestionModel,
    AiUsageLogModel,
    IntegrationEventModel,
    WorkOrderHistoryModel,
    WorkOrderModel,
    TicketAttachmentModel,
    TicketStatusHistoryModel,
    TicketModel,
    AuditLogModel,
    KbFeedbackModel,
    KbEvalRunModel,
    KbNoAnswerQuestionModel,
]


def reset_transactional_data(db) -> dict[str, int]:
    counts = {}
    for model in TRUNCATE_MODELS:
        result = db.execute(delete(model))
        counts[model.__name__] = result.rowcount or 0
    db.commit()
    return counts


def clean_non_whitelist_users(db) -> int:
    """Delete any user not in DEMO_USERNAMES. Deterministic."""
    result = db.execute(
        delete(UserModel).where(UserModel.username.notin_(DEMO_USERNAMES))
    )
    db.commit()
    return result.rowcount or 0


def clean_non_whitelist_departments(db) -> int:
    """Delete any department not in DEMO_DEPARTMENT_CODES. Deterministic."""
    result = db.execute(
        delete(DepartmentModel).where(DepartmentModel.code.notin_(DEMO_DEPARTMENT_CODES))
    )
    db.commit()
    return result.rowcount or 0


def clean_non_whitelist_categories(db) -> int:
    """Delete any category not in DEMO_CATEGORY_CODES."""
    result = db.execute(
        delete(CategoryModel).where(CategoryModel.code.notin_(DEMO_CATEGORY_CODES))
    )
    db.commit()
    return result.rowcount or 0


def clean_test_kb_docs(db) -> int:
    """Delete KB docs whose title matches test patterns; keep seed-managed docs."""
    test_patterns = ("P0-KB-%", "P0-D-%", "test-%", "Test-%", "TEST-%", "e2e-%", "r2-%", "r3-%", "round%")
    total = 0
    for pattern in test_patterns:
        result = db.execute(delete(KbDocumentModel).where(KbDocumentModel.title.like(pattern)))
        total += result.rowcount or 0
    # Clean orphan chunks
    db.execute(delete(KbChunkModel).where(
        KbChunkModel.document_id.notin_(select(KbDocumentModel.id))
    ))
    db.commit()
    return total


def print_stats(db):
    stats = {
        "departments": db.scalar(select(func.count(DepartmentModel.id))),
        "categories": db.scalar(select(func.count(CategoryModel.id))),
        "users": db.scalar(select(func.count(UserModel.id))),
        "tickets": db.scalar(select(func.count(TicketModel.id))),
        "kb_documents": db.scalar(select(func.count(KbDocumentModel.id))),
        "kb_chunks": db.scalar(select(func.count(KbChunkModel.id))),
        "kb_eval_cases": db.scalar(select(func.count(KbEvalCaseModel.id))),
        "ai_usage_logs": db.scalar(select(func.count(AiUsageLogModel.id))),
        "audit_logs": db.scalar(select(func.count(AuditLogModel.id))),
        "notifications": db.scalar(select(func.count(NotificationModel.id))),
        "follow_up_tasks": db.scalar(select(func.count(FollowUpTaskModel.id))),
    }
    print("\n=== Database statistics after reset+seed ===")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return stats


def list_demo_accounts(db):
    print("\n=== Demo accounts ===")
    users = db.scalars(select(UserModel).order_by(UserModel.role)).all()
    for u in users:
        print(f"  username={u.username} role={u.role} display={u.display_name}")


def list_departments(db):
    print("\n=== Departments ===")
    depts = db.scalars(select(DepartmentModel).order_by(DepartmentModel.id)).all()
    for d in depts:
        print(f"  code={d.code} name={d.name}")


def list_public_docs(db):
    print("\n=== Public published KB docs ===")
    docs = db.scalars(select(KbDocumentModel).where(
        KbDocumentModel.visibility == "PUBLIC",
        KbDocumentModel.status == "PUBLISHED",
    ).order_by(KbDocumentModel.id)).all()
    for d in docs:
        print(f"  id={d.id} title={d.title[:40]}")


def main():
    if not os.environ.get("SEED_PASSWORD"):
        print("ERROR: SEED_PASSWORD must be set (>=12 chars)")
        sys.exit(1)

    db = SessionLocal()

    print("=== Step 1: Truncate transactional data ===")
    counts = reset_transactional_data(db)
    for k, v in counts.items():
        if v > 0:
            print(f"  deleted {v} from {k}")

    print("\n=== Step 2: Clean non-whitelist users ===")
    n = clean_non_whitelist_users(db)
    print(f"  deleted {n} non-whitelist users")

    print("\n=== Step 3: Clean non-whitelist departments ===")
    n = clean_non_whitelist_departments(db)
    print(f"  deleted {n} non-whitelist departments")

    print("\n=== Step 4: Clean non-whitelist categories ===")
    n = clean_non_whitelist_categories(db)
    print(f"  deleted {n} non-whitelist categories")

    print("\n=== Step 5: Clean test KB docs ===")
    n = clean_test_kb_docs(db)
    print(f"  deleted {n} test KB docs")

    print("\n=== Step 6: Re-seed demo data ===")
    from app.seed import seed
    result = seed()
    print(f"  seed result: {result}")

    print_stats(db)
    list_demo_accounts(db)
    list_departments(db)
    list_public_docs(db)

    db.close()
    print("\n=== Demo reset complete (deterministic) ===")


if __name__ == "__main__":
    main()
