from collections.abc import Iterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..config import get_settings
from ..database import get_db
from ..malware_scanner import get_malware_scanner
from ..repositories.attachments import AttachmentRepository
from ..repositories.identity import AuditRepository
from ..repositories.postgres import PostgreSQLTicketRepository
from ..schemas import AttachmentDelete, AttachmentList, AttachmentRead, SuccessResponse
from ..services.attachment_service import AttachmentService
from ..storage import get_object_storage
from .dependencies import get_user_principal


router = APIRouter(tags=["attachments"])


def get_attachment_service(db: Session = Depends(get_db)) -> AttachmentService:
    return AttachmentService(
        PostgreSQLTicketRepository(db),
        AttachmentRepository(db),
        AuditRepository(db),
        get_object_storage(),
        get_malware_scanner(),
        get_settings(),
    )


@router.post(
    "/api/v1/tickets/{ticket_id}/attachments",
    response_model=SuccessResponse[AttachmentRead],
    status_code=status.HTTP_201_CREATED,
)
def upload_attachment(
    ticket_id: str,
    file: UploadFile = File(...),
    attachment_type: str = Form(...),
    visibility: str = Form("public"),
    principal: Principal = Depends(get_user_principal),
    service: AttachmentService = Depends(get_attachment_service),
):
    result = service.upload(
        ticket_id, principal, file.file, file.filename, file.content_type,
        attachment_type.strip(), visibility.strip(),
    )
    return SuccessResponse(data=result)


@router.get(
    "/api/v1/tickets/{ticket_id}/attachments",
    response_model=SuccessResponse[AttachmentList],
)
def list_attachments(
    ticket_id: str,
    principal: Principal = Depends(get_user_principal),
    service: AttachmentService = Depends(get_attachment_service),
):
    return SuccessResponse(data=service.list(ticket_id, principal))


def _stream_reader(reader) -> Iterator[bytes]:
    try:
        while True:
            chunk = reader.read(1024 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        close = getattr(reader, "close", None)
        if close:
            close()
        release = getattr(reader, "release_conn", None)
        if release:
            release()


@router.get("/api/v1/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: str,
    principal: Principal = Depends(get_user_principal),
    service: AttachmentService = Depends(get_attachment_service),
):
    result = service.download(attachment_id, principal)
    filename = result.attachment.original_filename
    suffix = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    disposition = f"attachment; filename=attachment.{suffix}; filename*=UTF-8''{quote(filename, safe='')}"
    return StreamingResponse(
        _stream_reader(result.reader),
        media_type=result.attachment.content_type,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(result.attachment.size_bytes),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/api/v1/attachments/{attachment_id}", response_model=SuccessResponse[dict[str, bool]])
def delete_attachment(
    attachment_id: str,
    payload: AttachmentDelete,
    principal: Principal = Depends(get_user_principal),
    service: AttachmentService = Depends(get_attachment_service),
):
    service.delete(attachment_id, payload.reason, principal)
    return SuccessResponse(data={"deleted": True})
