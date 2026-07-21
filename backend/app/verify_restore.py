"""Post-restore referential and object-storage verification."""
import os
import sys
from sqlalchemy import func, select, text

from .config import get_settings
from .database import SessionLocal
from .models import AuditLogModel, DepartmentModel, TicketAttachmentModel, TicketModel, TicketStatusHistoryModel, UserModel


def verify() -> dict[str, int]:
    models = {"tickets": TicketModel, "users": UserModel, "departments": DepartmentModel,
              "history": TicketStatusHistoryModel, "attachments": TicketAttachmentModel,
              "audit_logs": AuditLogModel}
    with SessionLocal() as db:
        counts = {name: int(db.scalar(select(func.count()).select_from(model)) or 0) for name, model in models.items()}
        broken = int(db.scalar(text("""
            SELECT count(*) FROM ticket_status_history h
            LEFT JOIN tickets t ON t.ticket_id=h.ticket_id WHERE t.ticket_id IS NULL
        """)) or 0)
        if broken:
            raise SystemExit(f"恢复验证失败：存在 {broken} 条孤立处理记录")
        if not counts["users"] or not counts["departments"]:
            raise SystemExit("恢复验证失败：用户或部门为空")
        ticket_id = os.getenv("VERIFY_TICKET_ID")
        if ticket_id:
            ticket = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket_id))
            history = int(db.scalar(select(func.count()).select_from(TicketStatusHistoryModel)
                                    .where(TicketStatusHistoryModel.ticket_id == ticket_id)) or 0)
            audit = int(db.scalar(select(func.count()).select_from(AuditLogModel)
                                  .where(AuditLogModel.resource_id == ticket_id)) or 0)
            if not ticket or not history or not audit:
                raise SystemExit(f"恢复验证失败：指定工单 {ticket_id} 或其处理/审计记录不完整")
            counts["verified_ticket_history"] = history
            counts["verified_ticket_audit"] = audit

        # Verify MinIO object integrity for active attachments
        attachments = list(db.scalars(select(TicketAttachmentModel).where(
            TicketAttachmentModel.deleted.is_(False)
        )).all())
        missing = []
        errors = []
        if attachments:
            try:
                from .storage import ObjectStorage
                settings = get_settings()
                storage = ObjectStorage(settings)
                for att in attachments:
                    try:
                        stat = storage.stat(att.object_key)
                        if att.file_size and stat.size != att.file_size:
                            errors.append(f"{att.object_key}: size mismatch db={att.file_size} actual={stat.size}")
                    except Exception:
                        missing.append(att.object_key)
            except Exception as exc:
                print(f"警告: 无法连接对象存储，跳过对象验证: {exc}", file=sys.stderr)
                counts["objects_skipped"] = len(attachments)
                return counts

        counts["objects_verified"] = len(attachments) - len(missing) - len(errors)
        counts["objects_missing"] = len(missing)
        counts["objects_size_mismatch"] = len(errors)
        if missing:
            print(f"缺失对象: {missing[:10]}", file=sys.stderr)
        if errors:
            print(f"损坏对象: {errors[:10]}", file=sys.stderr)
        if missing or errors:
            raise SystemExit(f"恢复验证失败：{len(missing)} 个对象缺失，{len(errors)} 个对象损坏")
        return counts


if __name__ == "__main__":
    result = verify()
    print("恢复完整性验证通过：", result)
