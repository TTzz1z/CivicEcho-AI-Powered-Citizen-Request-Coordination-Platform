"""Check PostgreSQL references and confirm restored S3 objects."""
from argparse import ArgumentParser
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import os

from sqlalchemy import func, select, text

from .database import SessionLocal
from .models import (
    AuditLogModel, DepartmentModel, KbDocumentModel, TicketAttachmentModel,
    TicketModel, TicketStatusHistoryModel, UserModel,
)
from .storage import get_kb_object_storage, get_object_storage


@dataclass(frozen=True)
class ObjectReference:
    kind: str
    key: str
    size: int | None
    digest: str | None = None


def object_references(db, *, attachment_bucket: str):
    attachments = select(TicketAttachmentModel).where(TicketAttachmentModel.is_deleted.is_(False))
    for item in db.scalars(attachments).yield_per(100):
        if item.storage_bucket != attachment_bucket:
            raise ValueError("Attachment database references a different storage bucket")
        yield ObjectReference("attachments", item.object_key, item.size_bytes, item.sha256)
    documents = select(KbDocumentModel).where(KbDocumentModel.storage_key.is_not(None))
    for doc in db.scalars(documents).yield_per(100):
        yield ObjectReference("knowledge_base", doc.storage_key, doc.file_size_bytes)


def object_stores():
    return {"attachments": get_object_storage(), "knowledge_base": get_kb_object_storage()}


def object_digest(store, key: str) -> str:
    digest = sha256()
    reader = store.open(key)
    try:
        with closing(reader):
            while chunk := reader.read(1024 * 1024):
                digest.update(chunk)
    finally:
        release_conn = getattr(reader, "release_conn", None)
        if release_conn is not None:
            release_conn()
    return digest.hexdigest()


def verify(*, database_only: bool = False) -> dict[str, int]:
    models = {
        "tickets": TicketModel, "users": UserModel, "departments": DepartmentModel,
        "history": TicketStatusHistoryModel, "attachments": TicketAttachmentModel,
        "audit_logs": AuditLogModel, "knowledge_base_documents": KbDocumentModel,
    }
    with SessionLocal() as db:
        counts = {name: int(db.scalar(select(func.count()).select_from(model)) or 0) for name, model in models.items()}
        broken = int(db.scalar(text("""
            SELECT count(*) FROM ticket_status_history h
            LEFT JOIN tickets t ON t.ticket_id=h.ticket_id WHERE t.ticket_id IS NULL
        """)) or 0)
        if broken:
            raise SystemExit(f"恢复验证失败：存在 {broken} 条孤立处理记录")
        ticket_id = os.getenv("VERIFY_TICKET_ID")
        if ticket_id:
            ticket = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket_id))
            history = int(db.scalar(select(func.count()).select_from(TicketStatusHistoryModel)
                                    .where(TicketStatusHistoryModel.ticket_id == ticket_id)) or 0)
            audit = int(db.scalar(select(func.count()).select_from(AuditLogModel)
                                  .where(AuditLogModel.resource_id == ticket_id)) or 0)
            if not ticket or not history or not audit:
                raise SystemExit("恢复验证失败：指定工单或其处理/审计记录不完整")
            counts["verified_ticket_history"] = history
            counts["verified_ticket_audit"] = audit

        if database_only:
            return counts
        counts["objects_verified"] = 0
        counts["objects_missing"] = 0
        counts["objects_mismatched"] = 0
        stores = object_stores()
        for item in object_references(db, attachment_bucket=stores["attachments"].bucket):
            store = stores[item.kind]
            try:
                size = store.size(item.key)
                if ((item.size is not None and size != item.size)
                        or (item.digest is not None and object_digest(store, item.key) != item.digest)):
                    counts["objects_mismatched"] += 1
                else:
                    counts["objects_verified"] += 1
            except Exception:
                counts["objects_missing"] += 1
        if counts["objects_missing"] or counts["objects_mismatched"]:
            raise SystemExit(
                f"恢复验证失败：{counts['objects_missing']} 个对象缺失或不可读，"
                f"{counts['objects_mismatched']} 个对象与数据库不一致"
            )
        return counts


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--database-only", action="store_true")
    args = parser.parse_args()
    print("数据库验证通过：" if args.database_only else "恢复完整性验证通过：",
          verify(database_only=args.database_only))
