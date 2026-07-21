import hashlib
import re
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO

from ..authorization import AuthorizationPolicy, Principal
from ..config import Settings
from ..errors import AttachmentNotFound, BusinessError, PermissionDenied, TicketNotFound
from ..malware_scanner import MalwareScanner
from ..models import TicketAttachmentModel
from ..repositories.attachments import AttachmentRepository
from ..schemas import AttachmentList, AttachmentRead
from ..storage import ObjectStorage


ATTACHMENT_TYPES = {"citizen_material", "site_photo", "official_document", "processing_proof", "other"}
MIME_BY_EXTENSION = {
    "jpg": {"image/jpeg"}, "jpeg": {"image/jpeg"}, "png": {"image/png"}, "webp": {"image/webp"},
    "pdf": {"application/pdf"}, "doc": {"application/msword"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xls": {"application/vnd.ms-excel"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "txt": {"text/plain"},
}


@dataclass
class AttachmentDownload:
    attachment: TicketAttachmentModel
    reader: object


class AttachmentService:
    def __init__(self, tickets, attachments: AttachmentRepository, audit, storage: ObjectStorage,
                 scanner: MalwareScanner, settings: Settings):
        self.tickets = tickets
        self.attachments = attachments
        self.audit = audit
        self.storage = storage
        self.scanner = scanner
        self.settings = settings

    def _audit(self, principal, action, outcome="success", resource_id=None, details=None):
        self.audit.log(principal, action, outcome, "attachment", resource_id, details)

    def _ticket(self, ticket_id: str):
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            raise TicketNotFound(ticket_id)
        return ticket

    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        name = PurePosixPath((filename or "").replace("\\", "/")).name
        name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
        if not name:
            raise BusinessError("INVALID_ATTACHMENT_NAME", "附件文件名不能为空", 422)
        return name[:255]

    @staticmethod
    def _signature_matches(extension: str, prefix: bytes) -> bool:
        if extension in {"jpg", "jpeg"}:
            return prefix.startswith(b"\xff\xd8\xff")
        if extension == "png":
            return prefix.startswith(b"\x89PNG\r\n\x1a\n")
        if extension == "webp":
            return prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"
        if extension == "pdf":
            return prefix.startswith(b"%PDF-")
        if extension in {"doc", "xls"}:
            return prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        if extension in {"docx", "xlsx"}:
            return prefix.startswith(b"PK\x03\x04")
        if extension == "txt":
            return b"\x00" not in prefix
        return False

    @staticmethod
    def _validate_ooxml(extension: str, staged: BinaryIO) -> bool:
        if extension not in {"docx", "xlsx"}:
            return True
        required = "word/document.xml" if extension == "docx" else "xl/workbook.xml"
        try:
            staged.seek(0)
            with zipfile.ZipFile(staged) as archive:
                entries = archive.infolist()
                names = {entry.filename for entry in entries}
                total_uncompressed = sum(entry.file_size for entry in entries)
                return (
                    len(entries) <= 10_000
                    and total_uncompressed <= 200 * 1024 * 1024
                    and "[Content_Types].xml" in names
                    and required in names
                )
        except (zipfile.BadZipFile, OSError):
            return False

    def _validate_upload_policy(self, principal: Principal, ticket, attachment_type: str, visibility: str):
        if principal.kind != "user":
            raise PermissionDenied()
        try:
            AuthorizationPolicy.require_view(principal, ticket)
        except PermissionDenied:
            self._audit(principal, "attachment_permission_denied", "denied", None,
                        {"ticket_id": ticket.ticket_id, "operation": "upload"})
            raise
        if attachment_type not in ATTACHMENT_TYPES:
            raise BusinessError("INVALID_ATTACHMENT_TYPE", "附件业务类型无效", 422)
        if visibility not in {"public", "internal"}:
            raise BusinessError("INVALID_ATTACHMENT_VISIBILITY", "附件可见范围无效", 422)
        if principal.role == "citizen":
            if visibility != "public" or attachment_type not in {"citizen_material", "other"}:
                raise PermissionDenied("市民只能上传公开的市民材料或其他补充材料")
            if ticket.status in {"closed", "rejected"}:
                raise BusinessError("TICKET_NOT_ACCEPTING_ATTACHMENTS", "已办结或不予受理的工单不能补充附件", 409)
        elif principal.role == "department_staff":
            if attachment_type == "citizen_material":
                raise PermissionDenied("部门人员不能以市民材料类型上传附件")
        elif principal.role not in {"agent", "admin"}:
            raise PermissionDenied()

    def upload(self, ticket_id: str, principal: Principal, file_stream: BinaryIO, filename: str | None,
               content_type: str | None, attachment_type: str, visibility: str) -> AttachmentRead:
        ticket = self._ticket(ticket_id)
        self._validate_upload_policy(principal, ticket, attachment_type, visibility)
        safe_name = self._safe_filename(filename)
        extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()
        if extension not in self.settings.allowed_attachment_extensions or extension not in MIME_BY_EXTENSION:
            raise BusinessError("ATTACHMENT_EXTENSION_NOT_ALLOWED", "不支持该附件扩展名", 415)
        if normalized_content_type not in self.settings.allowed_attachment_content_types:
            raise BusinessError("ATTACHMENT_CONTENT_TYPE_NOT_ALLOWED", "不支持该附件内容类型", 415)
        if normalized_content_type not in MIME_BY_EXTENSION[extension]:
            raise BusinessError("ATTACHMENT_TYPE_MISMATCH", "附件扩展名与内容类型不匹配", 415)

        maximum = self.settings.attachment_image_max_bytes if normalized_content_type.startswith("image/") else self.settings.attachment_max_bytes
        digest = hashlib.sha256()
        size = 0
        prefix = b""
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as staged:
            while True:
                chunk = file_stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    raise BusinessError(
                        "ATTACHMENT_TOO_LARGE", f"附件超过 {maximum // (1024 * 1024)} MB 限制", 413,
                        {"max_bytes": maximum},
                    )
                if len(prefix) < 512:
                    prefix += chunk[:512 - len(prefix)]
                digest.update(chunk)
                staged.write(chunk)
            if size == 0:
                raise BusinessError("EMPTY_ATTACHMENT", "附件内容不能为空", 422)
            if not self._signature_matches(extension, prefix):
                raise BusinessError("ATTACHMENT_SIGNATURE_MISMATCH", "附件实际内容与文件类型不匹配", 415)
            if not self._validate_ooxml(extension, staged):
                raise BusinessError("ATTACHMENT_SIGNATURE_MISMATCH", "Office 附件结构无效或解压规模超限", 415)

            scan = self.scanner.scan(staged, safe_name, normalized_content_type)
            if scan.status == "infected":
                self._audit(principal, "reject_infected_attachment", "denied", None,
                            {"ticket_id": ticket.ticket_id, "sha256": digest.hexdigest(), "engine": scan.engine})
                raise BusinessError("MALWARE_DETECTED", "附件未通过安全扫描", 422)
            if scan.status == "error" or (self.settings.malware_scan_require_clean and scan.status != "clean"):
                self._audit(principal, "attachment_scan_failed", "failed", None,
                            {"ticket_id": ticket.ticket_id, "engine": scan.engine})
                raise BusinessError("MALWARE_SCAN_UNAVAILABLE", "附件安全扫描暂时不可用", 503)

            attachment_id = str(uuid.uuid4())
            object_key = f"tickets/{ticket.ticket_id}/{attachment_id}"
            try:
                self.storage.put(object_key, staged, size, normalized_content_type)
                attachment = self.attachments.add(TicketAttachmentModel(
                    id=attachment_id,
                    ticket_id=ticket.ticket_id,
                    uploader_user_id=principal.user_id,
                    uploader_role=principal.role,
                    uploader_department_id=principal.department_id,
                    attachment_type=attachment_type,
                    visibility=visibility,
                    original_filename=safe_name,
                    content_type=normalized_content_type,
                    size_bytes=size,
                    sha256=digest.hexdigest(),
                    storage_provider="s3",
                    storage_bucket=self.storage.bucket,
                    object_key=object_key,
                    scan_status=scan.status,
                    scan_engine=scan.engine,
                    scan_detail=scan.detail,
                    scanned_at=scan.scanned_at,
                ))
            except Exception as exc:
                try:
                    self.storage.delete(object_key)
                except Exception:
                    pass
                self._audit(principal, "upload_attachment", "failed", attachment_id,
                            {"ticket_id": ticket.ticket_id, "error_type": type(exc).__name__})
                if isinstance(exc, BusinessError):
                    raise
                raise BusinessError("ATTACHMENT_STORAGE_UNAVAILABLE", "附件存储暂时不可用", 503) from exc

        self._audit(principal, "upload_attachment", resource_id=attachment.id,
                    details={"ticket_id": ticket.ticket_id, "visibility": visibility,
                             "attachment_type": attachment_type, "size_bytes": size, "sha256": attachment.sha256})
        return AttachmentRead.model_validate(attachment)

    def _require_read(self, principal: Principal, attachment: TicketAttachmentModel):
        ticket = self._ticket(attachment.ticket_id)
        try:
            AuthorizationPolicy.require_view(principal, ticket)
            if attachment.visibility == "internal" and principal.role not in {"agent", "department_staff", "admin"}:
                raise PermissionDenied("无权查看内部附件")
        except PermissionDenied:
            self._audit(principal, "attachment_permission_denied", "denied", attachment.id,
                        {"ticket_id": ticket.ticket_id, "operation": "read"})
            raise
        return ticket

    def list(self, ticket_id: str, principal: Principal) -> AttachmentList:
        ticket = self._ticket(ticket_id)
        try:
            AuthorizationPolicy.require_view(principal, ticket)
        except PermissionDenied:
            self._audit(principal, "attachment_permission_denied", "denied", None,
                        {"ticket_id": ticket.ticket_id, "operation": "list"})
            raise
        items = self.attachments.list_for_ticket(ticket.ticket_id)
        if principal.role not in {"agent", "department_staff", "admin"}:
            items = [item for item in items if item.visibility == "public"]
        return AttachmentList(items=[AttachmentRead.model_validate(item) for item in items], total=len(items))

    def download(self, attachment_id: str, principal: Principal) -> AttachmentDownload:
        attachment = self.attachments.get(attachment_id)
        if not attachment:
            raise AttachmentNotFound(attachment_id)
        self._require_read(principal, attachment)
        try:
            reader = self.storage.open(attachment.object_key)
        except Exception as exc:
            self._audit(principal, "download_attachment", "failed", attachment.id,
                        {"error_type": type(exc).__name__})
            raise BusinessError("ATTACHMENT_STORAGE_UNAVAILABLE", "附件存储暂时不可用", 503) from exc
        self._audit(principal, "download_attachment", resource_id=attachment.id,
                    details={"ticket_id": attachment.ticket_id})
        return AttachmentDownload(attachment, reader)

    def delete(self, attachment_id: str, reason: str, principal: Principal) -> None:
        attachment = self.attachments.get(attachment_id, include_deleted=True)
        if not attachment:
            raise AttachmentNotFound(attachment_id)
        ticket = self._require_read(principal, attachment)
        allowed = principal.role == "admin"
        allowed = allowed or attachment.uploader_user_id == principal.user_id
        allowed = allowed or (
            principal.role == "department_staff" and principal.department_id is not None
            and attachment.uploader_department_id == principal.department_id
            and ticket.assigned_department_id == principal.department_id
        )
        if not allowed:
            self._audit(principal, "attachment_permission_denied", "denied", attachment.id,
                        {"operation": "delete"})
            raise PermissionDenied("只能删除本人、本部门或管理员有权管理的附件")
        if not attachment.is_deleted:
            self.attachments.soft_delete(attachment, principal.user_id, reason.strip())
        try:
            self.storage.delete(attachment.object_key)
        except Exception as exc:
            self._audit(principal, "delete_attachment_object", "failed", attachment.id,
                        {"error_type": type(exc).__name__})
            raise BusinessError("ATTACHMENT_STORAGE_UNAVAILABLE", "附件已停止访问，但对象删除失败，请重试", 503) from exc
        self._audit(principal, "delete_attachment", resource_id=attachment.id,
                    details={"ticket_id": attachment.ticket_id, "reason": reason.strip()})
