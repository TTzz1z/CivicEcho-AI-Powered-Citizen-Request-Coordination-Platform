import asyncio
from hashlib import sha256
from io import BytesIO
import json
import subprocess
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from docx import Document
from pydantic import ValidationError
from pypdf import PdfWriter
from starlette.requests import Request
from starlette.responses import Response

from app import document_parser, object_snapshot, verify_restore
from app import main
from app.config import Settings
from app.malware_scanner import ClamdMalwareScanner
from app.storage import MinioObjectStorage


def test_cold_object_storage_does_not_probe_until_io(monkeypatch):
    client = Mock()
    client.get_object.side_effect = ConnectionRefusedError
    monkeypatch.setattr("minio.Minio", lambda *args, **kwargs: client)
    store = MinioObjectStorage("storage:9000", "test-access", "test-secret", "attachments")
    client.assert_not_called()
    assert client.mock_calls == []
    with pytest.raises(ConnectionRefusedError):
        store.open("sample.txt")
    client.get_object.assert_called_once_with("attachments", "sample.txt")
    client.bucket_exists.assert_not_called()


@pytest.mark.parametrize("missing_store", ["attachments", "knowledge_base"])
def test_restore_verifies_both_buckets_and_fails_when_an_object_is_missing(monkeypatch, missing_store):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def scalar(self, _statement):
            return 0

    payload = b"test"
    stores = {
        "attachments": Mock(bucket="attachments"),
        "knowledge_base": Mock(bucket="knowledge-base"),
    }
    for storage in stores.values():
        storage.size.return_value = len(payload)
        storage.open.side_effect = lambda _key: BytesIO(payload)
    refs = [
        verify_restore.ObjectReference("attachments", "ticket-object", len(payload), sha256(payload).hexdigest()),
        verify_restore.ObjectReference("knowledge_base", "kb-object", len(payload)),
    ]
    monkeypatch.setattr(verify_restore, "SessionLocal", Session)
    monkeypatch.setattr(verify_restore, "object_stores", lambda: stores)
    monkeypatch.setattr(verify_restore, "object_references", lambda db, **kwargs: iter(refs))
    monkeypatch.delenv("VERIFY_TICKET_ID", raising=False)
    assert verify_restore.verify()["objects_verified"] == 2
    stores[missing_store].size.side_effect = ConnectionRefusedError
    with pytest.raises(SystemExit, match="1 个对象缺失或不可读"):
        verify_restore.verify()


def test_object_snapshot_rejects_an_invalid_object_before_writing(tmp_path, monkeypatch):
    snapshot = tmp_path / "corrupt.zip"
    store = Mock()
    monkeypatch.setattr(object_snapshot, "object_stores", lambda: {"attachments": store})
    inventory = [{"kind": "attachments", "key": "fixture", "size": 6, "sha256": "incorrect"}]
    with ZipFile(snapshot, "w") as archive:
        archive.writestr("manifest.json", json.dumps(inventory))
        archive.writestr("objects/0", b"sample")
    with pytest.raises(ValueError, match="integrity check"):
        object_snapshot.restore(snapshot)
    store.put.assert_not_called()


def test_document_parser_executes_in_child_and_returns_bounded_timeout(monkeypatch):
    parsed = document_parser.parse_bytes("政务文书".encode(), "example.txt")
    assert parsed.text == "政务文书"
    assert parsed.ok

    def timeout(args, **kwargs):
        assert kwargs["timeout"] == document_parser.PARSE_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(document_parser.subprocess, "run", timeout)
    result = document_parser.parse_bytes(b"synthetic", "example.pdf")
    assert not result.ok
    assert result.file_type == "pdf"
    assert result.parser_notes == ["文档解析超时"]


def test_pdf_page_budget():
    document = PdfWriter()
    for _ in range(document_parser.MAX_PDF_PAGES + 1):
        document.add_blank_page(width=120, height=120)
    data = BytesIO()
    document.write(data)
    parsed = document_parser.parse_bytes(data.getvalue(), "book.pdf")
    assert not parsed.ok
    assert str(document_parser.MAX_PDF_PAGES) in parsed.parser_notes[0]


def test_valid_docx_passes_the_parser_limits():
    document = Document()
    document.add_heading("办事指南", level=1)
    document.add_paragraph("请提交申请表。")
    data = BytesIO()
    document.save(data)
    parsed = document_parser.parse_bytes(data.getvalue(), "guide.docx")
    assert parsed.ok
    assert "# 办事指南" in parsed.text
    assert "请提交申请表。" in parsed.text


def test_clamd_response_over_the_limit_is_rejected(monkeypatch):
    from contextlib import nullcontext

    fake_socket = Mock()
    fake_socket.recv.side_effect = lambda size: b"a" * size
    monkeypatch.setattr("app.malware_scanner.socket.create_connection",
                        lambda *args, **kwargs: nullcontext(fake_socket))
    result = ClamdMalwareScanner("scanner", 3310, 1).scan(BytesIO(b"sample"), "note.txt", "text/plain")
    assert result.status == "error"
    fake_socket.recv.assert_called_once()


def test_request_stream_without_length_respects_the_size_budget(monkeypatch):
    monkeypatch.setattr(main.settings, "max_request_body_bytes", 5)
    pieces = iter((b"abc", b"def"))

    async def receive():
        return {"type": "http.request", "body": next(pieces), "more_body": True}

    async def downstream(_request):
        pytest.fail("An oversized request reached the application")

    request = Request({
        "type": "http", "method": "POST", "scheme": "http", "path": "/api/v1/tickets",
        "headers": [],
    }, receive)
    response = asyncio.run(main.request_context(request, downstream))
    assert response.status_code == 413


def test_invalid_request_length_gets_a_controlled_response():
    async def downstream(_request):
        return Response(status_code=200)

    request = Request({
        "type": "http", "method": "POST", "scheme": "http", "path": "/api/v1/tickets",
        "headers": [(b"content-length", b"invalid")],
    })
    response = asyncio.run(main.request_context(request, downstream))
    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "INVALID_CONTENT_LENGTH"


@pytest.mark.parametrize("overrides", [
    {"database_url": "postgresql://dbuser:short@db/civicecho"},
    {"object_storage_secret_key": "short"},
])
def test_production_rejects_short_database_and_storage_credentials(overrides):
    fixture = dict(
        app_env="production",
        database_url="postgresql://dbuser:StrongFixtureCredential@db/civicecho",
        service_api_token="f4" * 18,
        jwt_secret="5c" * 18,
        object_storage_access_key="fixture-object-key",
        object_storage_secret_key="fixture-object-secret",
        cors_origins="https://civic.invalid",
        malware_scan_mode="clamd",
        malware_scan_url="clamav:3310",
        malware_scan_require_clean=True,
    )
    Settings(_env_file=None, **fixture)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(fixture | overrides))
