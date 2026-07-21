"""Credibility closeout: KB lock/publish, embedding isolation, malware, advice_id, WO tx."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.authorization import Principal
from app.database import SessionLocal
from app.embedding_client import EmbeddingResult, EmbeddingUsage
from app.errors import BusinessError
from app.main import app
from app.malware_scanner import ScanResult
from app.models import (
    AiSuggestionModel,
    DepartmentModel,
    KbChunkModel,
    KbDocumentModel,
    TicketModel,
    UserModel,
    WorkOrderModel,
)
from app.repositories.identity import AuditRepository, DepartmentRepository, UserRepository
from app.repositories.postgres import PostgreSQLTicketRepository
from app.repositories.work_orders import WorkOrderRepository
from app.security import create_access_token, hash_password
from app.services.kb_service import KnowledgeBaseService
from app.services.ticket_service import TicketService

client = TestClient(app)
PASSWORD = "V1-Closeout-Pytest-Only!"


def _embedding(*, fallback: bool = False) -> EmbeddingResult:
    if fallback:
        return EmbeddingResult(
            True, [0.01] * 1024, "fallback-hash", 1024,
            usage=EmbeddingUsage(unavailable=True), fallback=True,
        )
    return EmbeddingResult(
        True, [0.1] * 1024, "Qwen/Qwen3-Embedding-0.6B", 1024,
        usage=EmbeddingUsage(prompt_tokens=1, total_tokens=1), fallback=False,
    )


@pytest.fixture(scope="module")
def actors():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        department = db.scalar(select(DepartmentModel).where(DepartmentModel.name == "综合受理"))
        if department is None:
            department = db.scalar(select(DepartmentModel).where(DepartmentModel.is_active.is_(True)).limit(1))
        result = {}
        for name, role, department_id in (
            ("citizen", "citizen", None),
            ("agent", "agent", None),
            ("staff", "department_staff", department.id),
            ("admin", "admin", None),
        ):
            user = UserModel(
                username=f"v1_{name}_{suffix}",
                password_hash=hash_password(PASSWORD),
                display_name=f"v1-{name}", role=role,
                department_id=department_id, is_active=True,
            )
            db.add(user)
            db.flush()
            result[name] = {"id": user.id, "role": role}
        result["_department_id"] = department.id
        db.commit()
    return result


def headers(actor):
    return {"Authorization": f"Bearer {create_access_token(actor['id'], actor['role'])}"}


def test_embedding_fallback_not_written_to_pgvector():
    principal = Principal("user", 1, "admin_local", "admin", None)
    with SessionLocal() as db:
        doc = KbDocumentModel(
            title=f"embed-iso-{uuid4().hex[:8]}",
            kb_type="policy",
            file_type="text",
            visibility="PUBLIC",
            status="DRAFT",
            parse_status="pending",
            index_status="pending",
            raw_content="第一段。就业补贴政策。\n\n第二段。需要身份证。",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        svc = KnowledgeBaseService(db)
        mock_client = MagicMock()
        mock_client.embed_batch.side_effect = lambda texts: [_embedding(fallback=True) for _ in texts]
        mock_client.available = True
        store = MagicMock()
        with patch("app.services.kb_service.get_embedding_client", return_value=mock_client), \
             patch.object(KnowledgeBaseService, "_store_embedding", store), \
             patch("app.services.ai_usage_recorder.AiUsageRecorder.record_embedding_call"):
            svc._parse_and_index(doc, principal)
        store.assert_not_called()
        chunks = list(db.scalars(select(KbChunkModel).where(KbChunkModel.document_id == doc.id)).all())
        assert chunks
        assert all(c.embedding_fallback == "fallback_used" for c in chunks)
        rows = db.execute(
            text("SELECT embedding IS NULL AS empty FROM kb_chunks WHERE document_id=:id"),
            {"id": doc.id},
        ).all()
        assert all(r.empty for r in rows)


def test_index_in_progress_returns_409():
    principal = Principal("user", 1, "admin_local", "admin", None)
    with SessionLocal() as db:
        doc = KbDocumentModel(
            title=f"lock-{uuid4().hex[:8]}",
            kb_type="policy",
            file_type="text",
            visibility="PUBLIC",
            status="DRAFT",
            parse_status="parsing",
            index_status="building",
            raw_content="锁测试正文。",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        svc = KnowledgeBaseService(db)
        with pytest.raises(BusinessError) as exc:
            svc._parse_and_index(doc, principal)
        assert exc.value.code == "INDEX_IN_PROGRESS"
        assert exc.value.status_code == 409


def test_publish_failure_keeps_old_published_retrievable():
    principal = Principal("user", 1, "admin_local", "admin", None)
    with SessionLocal() as db:
        old = KbDocumentModel(
            title=f"old-{uuid4().hex[:8]}",
            kb_type="policy",
            file_type="text",
            visibility="PUBLIC",
            status="PUBLISHED",
            parse_status="done",
            index_status="ready",
            raw_content="旧版政策：路灯报修拨打12345。",
            active_index_batch="legacy-old",
        )
        db.add(old)
        db.commit()
        db.refresh(old)
        old_batch = "legacy-old"
        db.add(KbChunkModel(
            document_id=old.id, chunk_index=0, content="旧版政策：路灯报修拨打12345。",
            embedding_fallback="none", index_batch_id=old_batch,
        ))
        db.commit()

        new = KbDocumentModel(
            title=f"new-{uuid4().hex[:8]}",
            kb_type="policy",
            file_type="text",
            visibility="PUBLIC",
            status="DRAFT",
            parse_status="pending",
            index_status="pending",
            raw_content="新版政策内容。",
            replaces_doc_id=old.id,
        )
        db.add(new)
        db.commit()
        db.refresh(new)

        svc = KnowledgeBaseService(db)
        mock_client = MagicMock()
        mock_client.embed_batch.side_effect = RuntimeError("embed down")
        mock_client.available = True
        with patch("app.services.kb_service.get_embedding_client", return_value=mock_client), \
             patch("app.services.ai_usage_recorder.AiUsageRecorder.record_embedding_call"):
            with pytest.raises(BusinessError) as exc:
                svc._publish_internal(new, principal, "publish")
            assert exc.value.code == "INDEX_FAILED"

        db.refresh(old)
        db.refresh(new)
        assert old.status == "PUBLISHED"
        assert new.status == "DRAFT"
        assert new.index_status == "failed"
        live = list(db.scalars(select(KbChunkModel).where(
            KbChunkModel.document_id == old.id,
            KbChunkModel.index_batch_id == old_batch,
        )).all())
        assert live and "路灯" in live[0].content


def test_kb_upload_rejects_eicar_before_storage():
    principal = Principal("user", 1, "admin_local", "admin", None)
    with SessionLocal() as db:
        svc = KnowledgeBaseService(db)
        infected = ScanResult("infected", "clamd", "Eicar", datetime.now(timezone.utc))
        with patch("app.services.kb_service.get_malware_scanner") as scanner:
            scanner.return_value.scan.return_value = infected
            with pytest.raises(BusinessError) as exc:
                svc.upload_file(
                    principal,
                    file_bytes=b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
                    filename="note.txt",
                    mime_type="text/plain",
                    title="eicar",
                )
            assert exc.value.code == "MALWARE_DETECTED"
            assert exc.value.status_code == 422


def test_kb_upload_scanner_down_is_503_when_required():
    principal = Principal("user", 1, "admin_local", "admin", None)
    with SessionLocal() as db:
        svc = KnowledgeBaseService(db)
        err = ScanResult("error", "clamd", "down", datetime.now(timezone.utc))
        with patch("app.services.kb_service.get_malware_scanner") as scanner, \
             patch.object(svc.settings, "malware_scan_require_clean", True):
            scanner.return_value.scan.return_value = err
            with pytest.raises(BusinessError) as exc:
                svc.upload_file(
                    principal,
                    file_bytes=b"hello world content for kb",
                    filename="guide.txt",
                    mime_type="text/plain",
                    title="guide",
                )
            assert exc.value.code == "MALWARE_SCAN_UNAVAILABLE"
            assert exc.value.status_code == 503


def test_kb_upload_rejects_spoofed_pdf():
    principal = Principal("user", 1, "admin_local", "admin", None)
    with SessionLocal() as db:
        svc = KnowledgeBaseService(db)
        clean = ScanResult("clean", "disabled", None, datetime.now(timezone.utc))
        with patch("app.services.kb_service.get_malware_scanner") as scanner:
            scanner.return_value.scan.return_value = clean
            with pytest.raises(BusinessError) as exc:
                svc.upload_file(
                    principal,
                    file_bytes=b"not-a-real-pdf",
                    filename="fake.pdf",
                    mime_type="application/pdf",
                    title="fake",
                )
            assert exc.value.code == "ATTACHMENT_SIGNATURE_MISMATCH"


def test_kb_upload_rejects_zip_bomb_docx():
    """OOXML with too many entries must be rejected before MinIO."""
    import io
    import zipfile

    principal = Principal("user", 1, "admin_local", "admin", None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        zf.writestr("word/document.xml", "<w:document/>")
        for i in range(10_001):
            zf.writestr(f"word/media/x{i}.bin", b"x")
    payload = buf.getvalue()
    with SessionLocal() as db:
        svc = KnowledgeBaseService(db)
        clean = ScanResult("clean", "disabled", None, datetime.now(timezone.utc))
        put = MagicMock()
        with patch("app.services.kb_service.get_malware_scanner") as scanner, \
             patch("app.services.kb_service.get_kb_object_storage") as storage:
            scanner.return_value.scan.return_value = clean
            storage.return_value.put = put
            with pytest.raises(BusinessError) as exc:
                svc.upload_file(
                    principal,
                    file_bytes=payload,
                    filename="bomb.docx",
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    title="bomb",
                )
            assert exc.value.code == "ATTACHMENT_SIGNATURE_MISMATCH"
            put.assert_not_called()


def test_kb_upload_minio_failure_is_503(actors):
    principal = Principal("user", actors["admin"]["id"], "admin", "admin", None)
    with SessionLocal() as db:
        svc = KnowledgeBaseService(db)
        clean = ScanResult("clean", "disabled", None, datetime.now(timezone.utc))
        with patch("app.services.kb_service.get_malware_scanner") as scanner, \
             patch("app.services.kb_service.get_kb_object_storage") as storage:
            scanner.return_value.scan.return_value = clean
            storage.return_value.put.side_effect = RuntimeError("minio down")
            with pytest.raises(BusinessError) as exc:
                svc.upload_file(
                    principal,
                    file_bytes=b"policy body for minio failure test",
                    filename="guide.txt",
                    mime_type="text/plain",
                    title=f"minio-fail-{uuid4().hex[:8]}",
                )
            assert exc.value.code == "KB_STORAGE_UNAVAILABLE"
            assert exc.value.status_code == 503


def test_advice_id_required_and_duplicate_review(actors):
    """Missing advice_id → 422; wrong ticket → 404; duplicate → 409."""
    created = client.post("/api/v1/tickets", headers=headers(actors["citizen"]), json={
        "idempotency_key": str(uuid4()), "request_type": "求助",
        "description": f"advice-id closeout {uuid4().hex[:8]}", "location": "幸福路",
        "source": "v1-advice",
    })
    assert created.status_code == 201, created.text
    ticket_id = created.json()["data"]["ticket"]["ticket_id"]
    dept_id = actors["_department_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", headers=headers(actors["agent"]),
                json={"version": 1, "remark": "v1"})
    client.post(f"/api/v1/tickets/{ticket_id}/assign", headers=headers(actors["agent"]),
                json={"version": 2, "department_id": dept_id, "remark": "v1"})
    process_res = client.post(f"/api/v1/tickets/{ticket_id}/process",
                              headers=headers(actors["staff"]),
                              json={"version": 3, "remark": "v1"})
    assert process_res.status_code == 200, process_res.text

    missing = client.post(
        f"/api/v1/kb/tickets/{ticket_id}/advice/review",
        headers=headers(actors["staff"]),
        json={"decision": "adopted"},
    )
    assert missing.status_code == 422, missing.text

    advice_res = client.post(
        f"/api/v1/ai/tickets/{ticket_id}/case-advice",
        headers=headers(actors["staff"]),
    )
    assert advice_res.status_code == 200, advice_res.text
    advice_id = advice_res.json()["data"]["advice_id"]
    assert advice_id

    other = client.post("/api/v1/tickets", headers=headers(actors["citizen"]), json={
        "idempotency_key": str(uuid4()), "request_type": "求助",
        "description": f"other ticket {uuid4().hex[:8]}", "location": "幸福路",
        "source": "v1-advice-other",
    })
    other_id = other.json()["data"]["ticket"]["ticket_id"]
    wrong = client.post(
        f"/api/v1/kb/tickets/{other_id}/advice/review",
        headers=headers(actors["admin"]),
        json={"advice_id": advice_id, "decision": "adopted"},
    )
    assert wrong.status_code == 404, wrong.text

    first = client.post(
        f"/api/v1/kb/tickets/{ticket_id}/advice/review",
        headers=headers(actors["staff"]),
        json={"advice_id": advice_id, "decision": "adopted", "edit_summary": "采纳"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["advice_id"] == advice_id

    dup = client.post(
        f"/api/v1/kb/tickets/{ticket_id}/advice/review",
        headers=headers(actors["staff"]),
        json={"advice_id": advice_id, "decision": "rejected"},
    )
    assert dup.status_code == 409, dup.text
    assert dup.json()["error"]["code"] == "ADVICE_ALREADY_REVIEWED"

    with SessionLocal() as db:
        suggestion = db.get(AiSuggestionModel, advice_id)
        assert suggestion is not None
        assert suggestion.review_decision == "adopted"


def test_assign_rolls_back_when_work_order_create_fails(actors):
    """WorkOrder create failure must leave parent ticket status unchanged."""
    created = client.post("/api/v1/tickets", headers=headers(actors["citizen"]), json={
        "idempotency_key": str(uuid4()), "request_type": "投诉",
        "description": f"wo-tx {uuid4().hex[:8]}", "location": "幸福路",
        "source": "v1-wo-tx",
    })
    ticket_id = created.json()["data"]["ticket"]["ticket_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/accept", headers=headers(actors["agent"]),
                json={"version": 1, "remark": "v1"})
    dept_id = actors["_department_id"]

    with SessionLocal() as db:
        ticket = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket_id))
        assert ticket is not None
        assert ticket.status == "accepted"
        version_before = ticket.version
        svc = TicketService(
            PostgreSQLTicketRepository(db),
            DepartmentRepository(db),
            AuditRepository(db),
            UserRepository(db),
            work_orders=WorkOrderRepository(db),
        )
        principal = Principal("user", actors["agent"]["id"], "agent", "agent", None)
        with patch.object(WorkOrderRepository, "add", side_effect=RuntimeError("wo boom")):
            with pytest.raises(RuntimeError, match="wo boom"):
                svc.assign(ticket_id, version_before, "assign", dept_id, None, principal)
        db.expire_all()
        ticket2 = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket_id))
        assert ticket2.status == "accepted"
        assert ticket2.version == version_before
        orders = list(db.scalars(select(WorkOrderModel).where(WorkOrderModel.ticket_id == ticket_id)).all())
        assert orders == []


def test_concurrent_reindex_second_request_gets_409():
    """While building, a second FOR UPDATE path must refuse with INDEX_IN_PROGRESS."""
    principal = Principal("user", 1, "admin_local", "admin", None)
    with SessionLocal() as db:
        doc = KbDocumentModel(
            title=f"concurrent-{uuid4().hex[:8]}",
            kb_type="policy",
            file_type="text",
            visibility="PUBLIC",
            status="DRAFT",
            parse_status="pending",
            index_status="pending",
            raw_content="并发重建索引测试正文。",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        doc_id = doc.id

    # Session A marks building under lock, then Session B must 409.
    with SessionLocal() as db_a:
        locked = db_a.scalar(
            select(KbDocumentModel).where(KbDocumentModel.id == doc_id).with_for_update()
        )
        locked.index_status = "building"
        locked.parse_status = "parsing"
        db_a.commit()

    with SessionLocal() as db_b:
        svc = KnowledgeBaseService(db_b)
        doc_b = db_b.get(KbDocumentModel, doc_id)
        with pytest.raises(BusinessError) as exc:
            svc._parse_and_index(doc_b, principal)
        assert exc.value.code == "INDEX_IN_PROGRESS"
