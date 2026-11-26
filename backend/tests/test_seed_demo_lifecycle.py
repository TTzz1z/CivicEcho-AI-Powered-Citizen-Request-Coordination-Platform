"""Comprehensive tests for M5 realistic full-lifecycle demo seed and demo_reset MinIO guard."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import struct
import subprocess
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pypdf import PdfReader
from sqlalchemy import delete, func, select

from app import verify_restore
from app.ai_schemas import validate_handling_response, validate_triage_response
from app.authorization import Principal
from app.database import SessionLocal
from app.models import (
    AiSuggestionModel,
    AppealModel,
    AuditLogModel,
    FollowUpTaskModel,
    KbChunkModel,
    KbDocumentModel,
    KbEvalCaseModel,
    NotificationModel,
    NotificationOutboxModel,
    PhoneFollowUpRecordModel,
    TicketAttachmentModel,
    TicketFeedbackModel,
    TicketModel,
    TicketStatusHistoryModel,
    UserModel,
    WorkOrderHistoryModel,
    WorkOrderModel,
)
from app.repositories.aftercare import AftercareRepository, NotificationRepository
from app.repositories.analytics import AnalyticsRepository
from app.repositories.identity import AuditRepository
from app.repositories.postgres import PostgreSQLTicketRepository, TicketQuery
from app.seed import KB_DOCUMENTS, seed
from app.services.aftercare_service import AftercareService
from app.services.analytics_service import AnalyticsService
from app.services.ticket_service import TicketService
from app.storage import MinioObjectStorage, reset_object_storage_for_tests
from app.worker import ATTACHMENT_KEY
from scripts import demo_reset

UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
QT_16_RE = re.compile(r"^QT\d{16}$")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class FakeObjectStorage:
    """In-memory ObjectStorage fake supporting put/open/delete/size."""

    def __init__(self, bucket: str = "fake-attachments"):
        self.bucket = bucket
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, object_key: str, stream, length: int, content_type: str) -> None:
        stream.seek(0)
        data = stream.read(length)
        self.objects[object_key] = (data, content_type)

    def open(self, object_key: str):
        if object_key not in self.objects:
            raise FileNotFoundError(object_key)
        return io.BytesIO(self.objects[object_key][0])

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def size(self, object_key: str) -> int:
        if object_key not in self.objects:
            raise FileNotFoundError(object_key)
        return len(self.objects[object_key][0])


class UnreachableObjectStorage:
    """Simulates MinIO outage during DB-only CI test runs."""

    bucket = "unreachable-bucket"

    def size(self, object_key: str) -> int:
        raise ConnectionError(f"MinIO unreachable for {object_key}")

    def put(self, object_key: str, stream, length: int, content_type: str) -> None:
        raise ConnectionError(f"MinIO unreachable for {object_key}")


def _clean_database() -> None:
    """Wipe seeded transactional & KB rows while preserving migration-seeded categories."""
    with SessionLocal() as db:
        for model in (
            PhoneFollowUpRecordModel,
            FollowUpTaskModel,
            NotificationOutboxModel,
            NotificationModel,
            AppealModel,
            TicketFeedbackModel,
            AiSuggestionModel,
            WorkOrderHistoryModel,
            WorkOrderModel,
            TicketAttachmentModel,
            TicketStatusHistoryModel,
            TicketModel,
            AuditLogModel,
            KbEvalCaseModel,
            KbChunkModel,
            KbDocumentModel,
        ):
            db.execute(delete(model))
        db.execute(delete(UserModel).where(UserModel.username.in_([
            "citizen_local", "agent_local", "department_local", "admin_local",
        ])))
        db.commit()


@pytest.fixture
def isolated_seed_env(monkeypatch):
    reset_object_storage_for_tests()
    monkeypatch.setenv("SEED_PASSWORD", "civicecho-isolated-test-2468")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("AI_PROVIDER", "rules")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    fake_storage = FakeObjectStorage()
    monkeypatch.setattr("app.storage.get_object_storage", lambda: fake_storage)
    _clean_database()
    yield fake_storage


def _verify_png_chunks(raw: bytes) -> tuple[int, int]:
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    pos = 8
    seen_ihdr = False
    seen_idat = False
    seen_iend = False
    width = height = 0
    while pos < len(raw):
        length = struct.unpack("!I", raw[pos:pos + 4])[0]
        tag = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + length]
        crc_expected = struct.unpack("!I", raw[pos + 8 + length:pos + 12 + length])[0]
        assert (zlib.crc32(tag + data) & 0xFFFFFFFF) == crc_expected
        if tag == b"IHDR":
            width, height = struct.unpack("!II", data[:8])
            seen_ihdr = True
        elif tag == b"IDAT":
            seen_idat = True
        elif tag == b"IEND":
            seen_iend = True
        pos += 12 + length
    assert seen_ihdr and seen_idat and seen_iend
    assert width > 0 and height > 0
    return width, height


def test_seed_rejects_production_and_isolates_e2e(isolated_seed_env, monkeypatch):
    for env_name in ("production", "prod"):
        monkeypatch.setenv("APP_ENV", env_name)
        with pytest.raises(SystemExit):
            seed("demo")

    monkeypatch.setenv("APP_ENV", "development")
    counts = seed("e2e")
    assert counts["departments"] == 7
    assert counts["users"] == 4
    assert counts["kb_documents"] == len(KB_DOCUMENTS)
    assert counts["tickets"] == 0
    assert counts["kb_eval_cases"] == 0

    with SessionLocal() as db:
        assert db.scalar(select(func.count(TicketModel.id))) == 0
        assert db.scalar(select(func.count(TicketAttachmentModel.id))) == 0
        assert db.scalar(select(func.count(AiSuggestionModel.id))) == 0
        assert db.scalar(select(func.count(NotificationModel.id))) == 0
        assert db.scalar(select(func.count(FollowUpTaskModel.id))) == 0
        assert db.scalar(select(func.count(PhoneFollowUpRecordModel.id))) == 0
        assert db.scalar(select(func.count(AppealModel.id))) == 0
    assert isolated_seed_env.objects == {}


def test_seed_demo_idempotency_and_cli_banner(isolated_seed_env):
    first = seed("demo")
    with SessionLocal() as db:
        snap1 = {
            "tickets": db.scalar(select(func.count(TicketModel.id))),
            "history": db.scalar(select(func.count(TicketStatusHistoryModel.id))),
            "work_orders": db.scalar(select(func.count(WorkOrderModel.id))),
            "wo_history": db.scalar(select(func.count(WorkOrderHistoryModel.id))),
            "attachments": db.scalar(select(func.count(TicketAttachmentModel.id))),
            "feedbacks": db.scalar(select(func.count(TicketFeedbackModel.id))),
            "ai": db.scalar(select(func.count(AiSuggestionModel.id))),
            "notifications": db.scalar(select(func.count(NotificationModel.id))),
            "followups": db.scalar(select(func.count(FollowUpTaskModel.id))),
            "calls": db.scalar(select(func.count(PhoneFollowUpRecordModel.id))),
            "appeals": db.scalar(select(func.count(AppealModel.id))),
            "audits": db.scalar(select(func.count(AuditLogModel.id))),
        }

    second = seed("demo")
    with SessionLocal() as db:
        snap2 = {
            "tickets": db.scalar(select(func.count(TicketModel.id))),
            "history": db.scalar(select(func.count(TicketStatusHistoryModel.id))),
            "work_orders": db.scalar(select(func.count(WorkOrderModel.id))),
            "wo_history": db.scalar(select(func.count(WorkOrderHistoryModel.id))),
            "attachments": db.scalar(select(func.count(TicketAttachmentModel.id))),
            "feedbacks": db.scalar(select(func.count(TicketFeedbackModel.id))),
            "ai": db.scalar(select(func.count(AiSuggestionModel.id))),
            "notifications": db.scalar(select(func.count(NotificationModel.id))),
            "followups": db.scalar(select(func.count(FollowUpTaskModel.id))),
            "calls": db.scalar(select(func.count(PhoneFollowUpRecordModel.id))),
            "appeals": db.scalar(select(func.count(AppealModel.id))),
            "audits": db.scalar(select(func.count(AuditLogModel.id))),
        }

    assert first["tickets"] == 18
    assert second == first
    assert snap1 == snap2
    assert snap1["tickets"] == 18
    assert snap1["attachments"] == 3
    assert snap1["ai"] == 6
    assert snap1["notifications"] == 13
    assert snap1["followups"] == 4
    assert snap1["calls"] == 2
    assert snap1["appeals"] == 4
    assert snap1["feedbacks"] == 3
    assert snap1["audits"] >= 12


def test_seed_demo_18_tickets_14_days_statuses_sla_and_queues(isolated_seed_env):
    seed("demo")
    with SessionLocal() as db:
        tickets = list(db.scalars(select(TicketModel).order_by(TicketModel.created_at.desc())).all())
        assert len(tickets) == 18

        ids = {t.ticket_id for t in tickets}
        assert "QTDEMO000000000001" in ids
        for i in range(2, 19):
            tid = f"QT202611{i:010d}"
            assert tid in ids
            assert QT_16_RE.fullmatch(tid)

        # 14-day distribution in Asia/Shanghai (days 0..13 covered)
        today_sh = datetime.now(timezone.utc).astimezone(SHANGHAI_TZ).date()
        day_offsets = {(today_sh - t.created_at.astimezone(SHANGHAI_TZ).date()).days for t in tickets}
        assert day_offsets == set(range(14))

        # All 7 statuses, all 4 request types, all 7 departments
        assert {t.status for t in tickets} == {
            "pending", "accepted", "assigned", "processing", "resolved", "closed", "rejected",
        }
        assert {t.request_type for t in tickets} == {"投诉", "建议", "咨询", "求助"}
        dept_ids_used = {t.assigned_department_id for t in tickets if t.assigned_department_id is not None}
        assert len(dept_ids_used) == 7

        # Specific sub-states
        by_id = {t.ticket_id: t for t in tickets}
        assert by_id["QT2026110000000003"].needs_supplement is True
        assert by_id["QT2026110000000003"].collaboration_status == "awaiting_citizen"
        assert by_id["QT2026110000000005"].collaboration_status == "awaiting_dispatch"
        assert by_id["QT2026110000000009"].collaboration_status == "awaiting_summary"
        assert by_id["QT2026110000000010"].collaboration_status == "awaiting_review"
        assert isinstance(by_id["QT2026110000000010"].review_draft, dict)
        assert by_id["QT2026110000000015"].closure_type == "citizen_confirmed"
        assert by_id["QT2026110000000016"].closure_type == "phone_confirmed"
        assert by_id["QT2026110000000017"].closure_type == "admin_override"
        assert by_id["QT2026110000000018"].rejection_reason_code == "out_of_jurisdiction"
        assert by_id["QT2026110000000018"].suggested_channel

        # All 4 SLA states via TicketRepository & TicketService
        admin = db.scalar(select(UserModel).where(UserModel.username == "admin_local"))
        citizen = db.scalar(select(UserModel).where(UserModel.username == "citizen_local"))
        dept_staff = db.scalar(select(UserModel).where(UserModel.username == "department_local"))
        assert admin and citizen and dept_staff

        admin_p = Principal("user", admin.id, admin.username, admin.role, admin.department_id)
        citizen_p = Principal("user", citizen.id, citizen.username, citizen.role, citizen.department_id)
        dept_p = Principal("user", dept_staff.id, dept_staff.username, dept_staff.role, dept_staff.department_id)

        repo = PostgreSQLTicketRepository(db)
        for sla_state in ("on_track", "due_soon", "overdue", "paused"):
            res = repo.list(TicketQuery(sla_state=sla_state, page=1, page_size=50), admin_p)
            assert res.total >= 1, f"Missing SLA state: {sla_state}"

        ticket_svc = TicketService(repo)
        sla_states_presented = {ticket_svc._present(t, admin_p).sla_state for t in tickets}
        assert sla_states_presented == {"on_track", "due_soon", "overdue", "paused"}

        # citizen_local multi-stage visibility
        citizen_tickets = repo.list(TicketQuery(page=1, page_size=50), citizen_p)
        assert citizen_tickets.total >= 12
        assert {"pending", "accepted", "assigned", "processing", "resolved", "closed"} <= {
            t.status for t in citizen_tickets.items
        }

        # department_local queues (待办理, 办理中, 即将超时, 已超时, 被退回)
        assert repo.list(TicketQuery(status="assigned", page=1, page_size=20), dept_p).total >= 1
        assert repo.list(TicketQuery(status="processing", page=1, page_size=20), dept_p).total >= 1
        assert repo.list(TicketQuery(sla_state="due_soon", page=1, page_size=20), dept_p).total >= 1
        assert repo.list(TicketQuery(sla_state="overdue", page=1, page_size=20), dept_p).total >= 1
        assert repo.list(TicketQuery(work_queue="returned", page=1, page_size=20), dept_p).total >= 1

        # Analytics dashboard KPI & 14-day trend
        analytics = AnalyticsService(AnalyticsRepository(db), AuditRepository(db), ticket_svc).dashboard(admin_p)
        metrics_by_key = {m.key: m for m in analytics.metrics}
        assert metrics_by_key["total"].value == 18
        assert metrics_by_key["due_soon"].value >= 1
        assert metrics_by_key["overdue"].value >= 1
        assert metrics_by_key["avg_accept"].has_samples is True and metrics_by_key["avg_accept"].value > 0
        assert metrics_by_key["avg_resolve"].has_samples is True and metrics_by_key["avg_resolve"].value > 0
        assert len(analytics.intake_trend) == 14
        assert sum(pt.count for pt in analytics.intake_trend) == 18
        assert len(analytics.department_distribution) == 7
        assert len(analytics.request_type_distribution) == 4


def test_seed_demo_attachments_ai_notifications_aftercare_and_audits(isolated_seed_env):
    seed("demo")
    with SessionLocal() as db:
        # 1. Attachments (valid PDF & PNG, clean, matching SHA-256 & MinIO fake)
        attachments = list(db.scalars(select(TicketAttachmentModel)).all())
        assert len(attachments) == 3
        content_types = {a.content_type for a in attachments}
        assert content_types == {"application/pdf", "image/png"}
        for att in attachments:
            assert UUID4_RE.fullmatch(att.id)
            assert att.object_key == f"tickets/{att.ticket_id}/{att.id}"
            assert ATTACHMENT_KEY.fullmatch(att.object_key)
            assert att.scan_status == "clean"
            assert att.scan_engine == "seed-verified"
            assert att.storage_bucket == isolated_seed_env.bucket
            raw, _ = isolated_seed_env.objects[att.object_key]
            assert att.size_bytes == len(raw)
            assert att.sha256 == hashlib.sha256(raw).hexdigest()
            if att.content_type == "application/pdf":
                assert raw.startswith(b"%PDF-1.4")
                reader = PdfReader(io.BytesIO(raw))
                assert len(reader.pages) == 1
                box = reader.pages[0].mediabox
                assert float(box.width) > 0 and float(box.height) > 0
                assert att.ticket_id in (reader.pages[0].extract_text() or "")
            else:
                _verify_png_chunks(raw)

        refs = list(verify_restore.object_references(db, attachment_bucket=isolated_seed_env.bucket))
        assert len(refs) == 3
        for ref in refs:
            assert isolated_seed_env.size(ref.key) == ref.size
            assert hashlib.sha256(isolated_seed_env.objects[ref.key][0]).hexdigest() == ref.digest

        # 2. AI Suggestions (advisory_only=True, schema-validated, review decisions)
        ais = list(db.scalars(select(AiSuggestionModel)).all())
        assert len(ais) == 6
        assert {a.review_decision for a in ais} == {
            None, "helpful", "adopted", "adopted_with_edits", "rejected",
        }
        for item in ais:
            parsed = json.loads(item.result_json)
            assert parsed["advisory_only"] is True
            if item.suggestion_type == "triage_assistant":
                assert validate_triage_response(parsed).ok
            else:
                assert validate_handling_response(parsed, facts_sufficient=False).ok

        # 3. Notifications (unread + read across all 4 demo users)
        for uname in ("citizen_local", "agent_local", "department_local", "admin_local"):
            user = db.scalar(select(UserModel).where(UserModel.username == uname))
            assert user
            notifs = list(db.scalars(select(NotificationModel).where(
                NotificationModel.recipient_user_id == user.id,
            )).all())
            assert {"unread", "read"} <= {n.status for n in notifs}, f"Missing read/unread for {uname}"

        # 4. Follow-ups, phone records, feedbacks & appeals
        tasks = list(db.scalars(select(FollowUpTaskModel)).all())
        assert {t.status for t in tasks} == {"pending", "in_progress", "completed", "cancelled"}
        calls = list(db.scalars(select(PhoneFollowUpRecordModel)).all())
        assert {(c.contact_result, c.outcome) for c in calls} == {
            ("no_answer", "needs_followup"),
            ("reached", "confirmed"),
        }
        appeals = list(db.scalars(select(AppealModel)).all())
        assert {a.status for a in appeals} == {"submitted", "reprocessing", "completed", "rejected"}

        # Ensure AftercareService can list follow-ups and appeals cleanly for admin/agent
        admin = db.scalar(select(UserModel).where(UserModel.username == "admin_local"))
        admin_p = Principal("user", admin.id, admin.username, admin.role, admin.department_id)
        aftercare = AftercareService(AftercareRepository(db), NotificationRepository(db), AuditRepository(db))
        assert aftercare.list_follow_ups(admin_p, 1, 20, None).total == 4
        assert aftercare.list_appeals(admin_p, 1, 20, None).total == 4


def test_seed_skips_dangling_attachments_when_minio_unreachable(isolated_seed_env, monkeypatch):
    monkeypatch.setattr("app.storage.get_object_storage", lambda: UnreachableObjectStorage())
    counts = seed("demo")
    assert counts["tickets"] == 18
    assert counts["attachments"] == 0
    with SessionLocal() as db:
        assert db.scalar(select(func.count(TicketAttachmentModel.id))) == 0


def test_demo_reset_cleans_tickets_prefix_only_for_attachments(monkeypatch):
    removed: list[tuple[str, str]] = []

    class FakeObj:
        def __init__(self, name: str):
            self.object_name = name

    class FakeClient:
        def __init__(self, label: str):
            self.label = label

        def list_objects(self, bucket: str, prefix: str, recursive: bool = True):
            if prefix == "tickets/":
                return [FakeObj("tickets/QT1/uuid-1")]
            if prefix == "docs/":
                return [FakeObj("docs/1/file.pdf"), FakeObj("docs/1/test-doc.pdf")]
            return []

        def remove_object(self, bucket: str, name: str):
            removed.append((bucket, name))

    class FakeStore:
        def __init__(self, bucket: str, label: str):
            self.bucket = bucket
            self._client = FakeClient(label)

    monkeypatch.setattr("app.storage.get_object_storage", lambda: FakeStore("att-bucket", "att"))
    monkeypatch.setattr("app.storage.get_kb_object_storage", lambda: FakeStore("kb-bucket", "kb"))

    demo_reset._cleanup_minio_demo_prefixes()
    assert ("att-bucket", "tickets/QT1/uuid-1") in removed
    assert ("kb-bucket", "tickets/QT1/uuid-1") not in removed
    assert ("kb-bucket", "docs/1/test-doc.pdf") in removed
    assert ("kb-bucket", "docs/1/file.pdf") not in removed


def test_seed_cli_prints_completion_banner(isolated_seed_env, monkeypatch):
    # Verify CLI entrypoint output contains 'Seed 完成' (required by scripts/check-demo.ps1).
    env = os.environ.copy()
    env.update({
        "SEED_PASSWORD": "civicecho-isolated-test-2468",
        "SEED_PROFILE": "e2e",
        "APP_ENV": "development",
        "AI_API_KEY": "",
        "AI_PROVIDER": "rules",
        "EMBEDDING_API_KEY": "",
    })
    backend_dir = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "app.seed"],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Seed 完成" in proc.stdout


def test_seed_demo_attachments_isolated_real_minio_bucket(monkeypatch):
    """If local MinIO (127.0.0.1:29000) is reachable, test real upload into isolated bucket and clean up."""
    bucket = "tingting-attachments-m5test"
    endpoint = os.getenv("TEST_MINIO_ENDPOINT", "127.0.0.1:29000")
    access_key = os.getenv("OBJECT_STORAGE_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("OBJECT_STORAGE_SECRET_KEY", "minioadmin")
    store = MinioObjectStorage(endpoint, access_key, secret_key, bucket, secure=False, timeout_seconds=2)
    try:
        store.bucket_exists()
    except Exception:
        pytest.skip(f"Local MinIO at {endpoint} not reachable; skipping live isolated bucket test")

    reset_object_storage_for_tests()
    monkeypatch.setenv("SEED_PASSWORD", "civicecho-isolated-test-2468")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("AI_PROVIDER", "rules")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    monkeypatch.setattr("app.storage.get_object_storage", lambda: store)
    _clean_database()
    try:
        counts = seed("demo")
        assert counts["attachments"] == 3
        # Idempotent second run against real MinIO
        counts2 = seed("demo")
        assert counts2["attachments"] == 3
        with SessionLocal() as db:
            refs = list(verify_restore.object_references(db, attachment_bucket=bucket))
            assert len(refs) == 3
            for ref in refs:
                assert store.size(ref.key) == ref.size
                assert verify_restore.object_digest(store, ref.key) == ref.digest
    finally:
        try:
            for obj in list(store._client.list_objects(bucket, recursive=True)):
                store._client.remove_object(bucket, obj.object_name)
            if store.bucket_exists():
                store._client.remove_bucket(bucket)
        except Exception:
            pass
