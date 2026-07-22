"""Demo environment: deterministic one-click reset + seed.

Usage:
    SEED_PASSWORD=tingting-seed-demo-2026 \\
      python -m scripts.demo_reset --confirm-reset

Safety guards (Round-1):
- Refuses APP_ENV=production|prod
- Database name must be in the demo/e2e/ci whitelist
- Requires --confirm-reset or CONFIRM_DEMO_RESET=YES

This script is intentionally destructive. NEVER run it against a production database.
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

ALLOWED_DEMO_DB_NAMES = frozenset({
    "tingting",
    "tingting_e2e",
    "tingting_ci",
    "tingting_test",
})

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
    # L1
    "CSGL",
    # L2
    "CSGL-GGSS",
    "CSGL-GS",
    "CSGL-HW",
    "CSGL-YL",
    # L3 公共设施
    "CSGL-GGSS-LD",
    "CSGL-GGSS-DL",
    "CSGL-GGSS-JG",
    "CSGL-GGSS-GD",
    # L3 供水排水
    "CSGL-GS-TS",
    "CSGL-GS-JS",
    # L3 市容环卫
    "CSGL-HW-LJ",
    "CSGL-HW-ZW",
    # L3 园林绿化
    "CSGL-YL-LH",
    "CSGL-YL-SM",
}


def _database_name(database_url: str) -> str:
    parsed = urlparse(database_url)
    name = (parsed.path or "").lstrip("/")
    return name.split("?")[0].strip()


def assert_safe_to_reset(*, confirm_reset: bool) -> None:
    """Hard guards against wiping a non-demo database.

    Uses process environment only so production refusal works before Settings
    validators (malware scan etc.) are loaded.
    """
    if not os.environ.get("SEED_PASSWORD"):
        print("ERROR: SEED_PASSWORD must be set (>=12 chars)")
        sys.exit(1)

    app_env = (os.environ.get("APP_ENV") or "development").strip().lower()
    if app_env in {"production", "prod"}:
        print(f"ERROR: demo_reset refused when APP_ENV={app_env}")
        sys.exit(2)

    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        print("ERROR: DATABASE_URL must be set for demo_reset")
        sys.exit(2)

    db_name = _database_name(database_url)
    if db_name not in ALLOWED_DEMO_DB_NAMES:
        print(
            f"ERROR: database '{db_name}' is not in the demo whitelist "
            f"{sorted(ALLOWED_DEMO_DB_NAMES)}"
        )
        sys.exit(2)

    confirmed = confirm_reset or os.environ.get("CONFIRM_DEMO_RESET", "").upper() == "YES"
    if not confirmed:
        print("ERROR: pass --confirm-reset or set CONFIRM_DEMO_RESET=YES")
        sys.exit(2)


def _load_models():
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

    truncate_models = [
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
    return {
        "SessionLocal": SessionLocal,
        "delete": delete,
        "select": select,
        "func": func,
        "truncate_models": truncate_models,
        "UserModel": UserModel,
        "DepartmentModel": DepartmentModel,
        "CategoryModel": CategoryModel,
        "KbDocumentModel": KbDocumentModel,
        "KbChunkModel": KbChunkModel,
        "TicketModel": TicketModel,
        "AiUsageLogModel": AiUsageLogModel,
        "AuditLogModel": AuditLogModel,
        "NotificationModel": NotificationModel,
        "FollowUpTaskModel": FollowUpTaskModel,
        "KbEvalCaseModel": KbEvalCaseModel,
    }


def _cleanup_minio_demo_prefixes() -> None:
    """Best-effort purge of demo/test object prefixes. Never fails the reset."""
    try:
        from app.storage import get_kb_object_storage, get_object_storage
    except Exception as exc:  # pragma: no cover - optional soft path
        print(f"  skip MinIO cleanup (import): {exc}")
        return

    prefixes = ("demo/", "e2e/", "test/", "docs/")
    for label, factory in (
        ("attachments", get_object_storage),
        ("kb", get_kb_object_storage),
    ):
        try:
            storage = factory()
            client = getattr(storage, "_client", None)
            bucket = getattr(storage, "bucket", None)
            if client is None or not bucket:
                print(f"  skip MinIO {label}: client unavailable")
                continue
            removed = 0
            for prefix in prefixes:
                try:
                    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
                        name = getattr(obj, "object_name", None)
                        if not name:
                            continue
                        # Keep durable seeded KB objects under docs/<id>/; only wipe test-ish keys.
                        if prefix == "docs/" and "/test-" not in name and "/e2e-" not in name and "/r2-" not in name:
                            continue
                        client.remove_object(bucket, name)
                        removed += 1
                except Exception as prefix_exc:
                    print(f"  MinIO {label} prefix {prefix}: {prefix_exc}")
            print(f"  MinIO {label}: removed {removed} demo/test objects")
        except Exception as exc:
            print(f"  skip MinIO {label} cleanup: {exc}")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Deterministic demo DB reset + seed")
    parser.add_argument(
        "--confirm-reset",
        action="store_true",
        help="Required confirmation that this is an intentional destructive reset",
    )
    args = parser.parse_args(argv)
    assert_safe_to_reset(confirm_reset=args.confirm_reset)

    ctx = _load_models()
    SessionLocal = ctx["SessionLocal"]
    delete = ctx["delete"]
    select = ctx["select"]
    func = ctx["func"]
    db = SessionLocal()

    print("=== Step 1: Truncate transactional data ===")
    counts = {}
    for model in ctx["truncate_models"]:
        result = db.execute(delete(model))
        counts[model.__name__] = result.rowcount or 0
    db.commit()
    for k, v in counts.items():
        if v > 0:
            print(f"  deleted {v} from {k}")

    print("\n=== Step 2: Clean non-whitelist users ===")
    result = db.execute(
        delete(ctx["UserModel"]).where(ctx["UserModel"].username.notin_(DEMO_USERNAMES))
    )
    db.commit()
    print(f"  deleted {result.rowcount or 0} non-whitelist users")

    print("\n=== Step 3: Clean non-whitelist departments ===")
    result = db.execute(
        delete(ctx["DepartmentModel"]).where(
            ctx["DepartmentModel"].code.notin_(DEMO_DEPARTMENT_CODES)
        )
    )
    db.commit()
    print(f"  deleted {result.rowcount or 0} non-whitelist departments")

    print("\n=== Step 4: Clean non-whitelist categories ===")
    result = db.execute(
        delete(ctx["CategoryModel"]).where(
            ctx["CategoryModel"].code.notin_(DEMO_CATEGORY_CODES)
        )
    )
    db.commit()
    print(f"  deleted {result.rowcount or 0} non-whitelist categories")

    print("\n=== Step 5: Clean test KB docs ===")
    KbDocumentModel = ctx["KbDocumentModel"]
    KbChunkModel = ctx["KbChunkModel"]
    total = 0
    for pattern in ("P0-KB-%", "P0-D-%", "test-%", "Test-%", "TEST-%", "e2e-%", "r2-%", "r3-%", "round%"):
        result = db.execute(delete(KbDocumentModel).where(KbDocumentModel.title.like(pattern)))
        total += result.rowcount or 0
    db.execute(delete(KbChunkModel).where(
        KbChunkModel.document_id.notin_(select(KbDocumentModel.id))
    ))
    db.commit()
    print(f"  deleted {total} test KB docs")

    print("\n=== Step 5b: Optional MinIO demo-prefix cleanup ===")
    _cleanup_minio_demo_prefixes()

    print("\n=== Step 6: Re-seed demo data ===")
    from app.seed import seed
    result = seed()
    print(f"  seed result: {result}")

    stats = {
        "departments": db.scalar(select(func.count(ctx["DepartmentModel"].id))),
        "categories": db.scalar(select(func.count(ctx["CategoryModel"].id))),
        "users": db.scalar(select(func.count(ctx["UserModel"].id))),
        "tickets": db.scalar(select(func.count(ctx["TicketModel"].id))),
        "kb_documents": db.scalar(select(func.count(KbDocumentModel.id))),
        "kb_chunks": db.scalar(select(func.count(KbChunkModel.id))),
        "kb_eval_cases": db.scalar(select(func.count(ctx["KbEvalCaseModel"].id))),
        "ai_usage_logs": db.scalar(select(func.count(ctx["AiUsageLogModel"].id))),
        "audit_logs": db.scalar(select(func.count(ctx["AuditLogModel"].id))),
        "notifications": db.scalar(select(func.count(ctx["NotificationModel"].id))),
        "follow_up_tasks": db.scalar(select(func.count(ctx["FollowUpTaskModel"].id))),
    }
    print("\n=== Database statistics after reset+seed ===")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\n=== Demo accounts ===")
    for u in db.scalars(select(ctx["UserModel"]).order_by(ctx["UserModel"].role)).all():
        print(f"  username={u.username} role={u.role} display={u.display_name}")

    print("\n=== Departments ===")
    for d in db.scalars(select(ctx["DepartmentModel"]).order_by(ctx["DepartmentModel"].id)).all():
        print(f"  code={d.code} name={d.name}")

    print("\n=== Public published KB docs ===")
    docs = db.scalars(select(KbDocumentModel).where(
        KbDocumentModel.visibility == "PUBLIC",
        KbDocumentModel.status == "PUBLISHED",
    ).order_by(KbDocumentModel.id)).all()
    for d in docs:
        print(f"  id={d.id} title={d.title[:40]}")

    db.close()
    print("\n=== Demo reset complete (deterministic) ===")


if __name__ == "__main__":
    main()
