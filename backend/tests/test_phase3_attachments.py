import io
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.attachments import get_attachment_service
from app.api.dependencies import get_user_principal
from app.authorization import Principal
from app.config import Settings
from app.errors import BusinessError, PermissionDenied
from app.malware_scanner import ScanResult
from app.main import app
from app.services.attachment_service import AttachmentService


class Tickets:
    def __init__(self):
        self.ticket = SimpleNamespace(
            ticket_id="QT2026071400000001", creator_user_id=1, anonymous_creator_key=None,
            assigned_department_id=8, status="processing",
        )

    def get(self, ticket_id):
        return self.ticket if ticket_id.upper() == self.ticket.ticket_id else None


class Attachments:
    def __init__(self):
        self.items = {}

    def add(self, item):
        item.created_at = datetime.now(timezone.utc)
        item.is_deleted = False
        self.items[item.id] = item
        return item

    def get(self, attachment_id, include_deleted=False):
        item = self.items.get(attachment_id)
        if item and (include_deleted or not item.is_deleted):
            return item
        return None

    def list_for_ticket(self, ticket_id):
        return [item for item in self.items.values() if item.ticket_id == ticket_id and not item.is_deleted]

    def soft_delete(self, attachment, user_id, reason):
        attachment.is_deleted = True
        attachment.deleted_by_user_id = user_id
        attachment.delete_reason = reason


class Storage:
    bucket = "test-attachments"

    def __init__(self):
        self.objects = {}

    def put(self, key, stream, length, content_type):
        stream.seek(0)
        self.objects[key] = stream.read()

    def open(self, key):
        return io.BytesIO(self.objects[key])

    def delete(self, key):
        self.objects.pop(key, None)


class Scanner:
    def __init__(self, status="clean"):
        self.status = status

    def scan(self, stream, filename, content_type):
        return ScanResult(self.status, "test-engine", None, datetime.now(timezone.utc))


class Audit:
    def __init__(self):
        self.events = []

    def log(self, principal, action, outcome="success", resource_type=None, resource_id=None, details=None):
        self.events.append((action, outcome, resource_id, details))


def png(content=b"evidence"):
    return io.BytesIO(b"\x89PNG\r\n\x1a\n" + content)


def make_service(scan_status="clean", **setting_overrides):
    settings = Settings(_env_file=None, **setting_overrides)
    attachments, storage, audit = Attachments(), Storage(), Audit()
    service = AttachmentService(Tickets(), attachments, audit, storage, Scanner(scan_status), settings)
    return service, attachments, storage, audit


CITIZEN = Principal("user", 1, "citizen", "citizen", None)
STAFF = Principal("user", 8, "staff", "department_staff", 8)
ADMIN = Principal("user", 99, "admin", "admin", None)


def test_citizen_upload_download_and_soft_delete_public_attachment():
    service, attachments, storage, audit = make_service()
    uploaded = service.upload(
        "QT2026071400000001", CITIZEN, png(), "现场照片.png", "image/png",
        "citizen_material", "public",
    )
    assert uploaded.size_bytes > 8 and uploaded.scan_status == "clean"
    assert service.list(uploaded.ticket_id, CITIZEN).total == 1
    download = service.download(uploaded.id, CITIZEN)
    assert download.reader.read().startswith(b"\x89PNG")
    service.delete(uploaded.id, "误传文件", CITIZEN)
    assert attachments.items[uploaded.id].is_deleted is True
    assert storage.objects == {}
    assert {event[0] for event in audit.events} >= {"upload_attachment", "download_attachment", "delete_attachment"}


def test_internal_attachment_is_hidden_from_citizen_but_visible_to_department():
    service, _, _, _ = make_service()
    uploaded = service.upload(
        "QT2026071400000001", STAFF, png(), "处置前现场.png", "image/png",
        "site_photo", "internal",
    )
    assert service.list(uploaded.ticket_id, STAFF).total == 1
    assert service.list(uploaded.ticket_id, CITIZEN).total == 0
    with pytest.raises(PermissionDenied):
        service.download(uploaded.id, CITIZEN)
    assert service.download(uploaded.id, ADMIN).reader.read().startswith(b"\x89PNG")


def test_citizen_cannot_create_internal_or_department_evidence():
    service, _, _, _ = make_service()
    with pytest.raises(PermissionDenied):
        service.upload(
            "QT2026071400000001", CITIZEN, png(), "证明.png", "image/png",
            "processing_proof", "internal",
        )


def test_malware_and_spoofed_content_are_rejected_before_object_storage():
    service, _, storage, audit = make_service(scan_status="infected")
    with pytest.raises(BusinessError) as infected:
        service.upload(
            "QT2026071400000001", STAFF, png(), "现场.png", "image/png", "site_photo", "public",
        )
    assert infected.value.code == "MALWARE_DETECTED"
    assert storage.objects == {}
    assert any(event[0] == "reject_infected_attachment" for event in audit.events)

    clean_service, _, clean_storage, _ = make_service()
    with pytest.raises(BusinessError) as spoofed:
        clean_service.upload(
            "QT2026071400000001", STAFF, io.BytesIO(b"not-a-png"), "fake.png", "image/png",
            "site_photo", "public",
        )
    assert spoofed.value.code == "ATTACHMENT_SIGNATURE_MISMATCH"
    assert clean_storage.objects == {}


def test_size_limit_is_enforced_while_streaming():
    service, _, storage, _ = make_service(attachment_image_max_bytes=16)
    with pytest.raises(BusinessError) as too_large:
        service.upload(
            "QT2026071400000001", STAFF, png(b"x" * 20), "large.png", "image/png",
            "site_photo", "public",
        )
    assert too_large.value.code == "ATTACHMENT_TOO_LARGE"
    assert storage.objects == {}


def test_attachment_http_upload_list_download_and_delete_contract():
    service, _, _, _ = make_service()
    app.dependency_overrides[get_attachment_service] = lambda: service
    app.dependency_overrides[get_user_principal] = lambda: STAFF
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/tickets/QT2026071400000001/attachments",
                data={"attachment_type": "site_photo", "visibility": "public"},
                files={"file": ("现场.png", b"\x89PNG\r\n\x1a\nevidence", "image/png")},
            )
            assert created.status_code == 201
            attachment_id = created.json()["data"]["id"]
            listed = client.get("/api/v1/tickets/QT2026071400000001/attachments")
            assert listed.json()["data"]["total"] == 1
            downloaded = client.get(f"/api/v1/attachments/{attachment_id}/download")
            assert downloaded.status_code == 200
            assert downloaded.content.startswith(b"\x89PNG")
            assert downloaded.headers["x-content-type-options"] == "nosniff"
            deleted = client.request(
                "DELETE", f"/api/v1/attachments/{attachment_id}", json={"reason": "测试删除"},
            )
            assert deleted.json()["data"] == {"deleted": True}
    finally:
        app.dependency_overrides.clear()
