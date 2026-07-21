"""Atomic KB index switch: keep live chunks until rebuild succeeds."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import select

from app.authorization import Principal
from app.database import SessionLocal
from app.embedding_client import EmbeddingResult, EmbeddingUsage
from app.models import KbChunkModel, KbDocumentModel
from app.services.kb_service import KnowledgeBaseService


def _embedding(*, fail: bool = False, fallback: bool = False) -> EmbeddingResult:
    if fail:
        return EmbeddingResult(False, None, "err", 1024, error="boom", fallback=False)
    if fallback:
        return EmbeddingResult(
            True, [0.01] * 1024, "fallback-hash", 1024,
            usage=EmbeddingUsage(unavailable=True), fallback=True,
        )
    return EmbeddingResult(
        True, [0.1] * 1024, "Qwen/Qwen3-Embedding-0.6B", 1024,
        usage=EmbeddingUsage(prompt_tokens=1, total_tokens=1), fallback=False,
    )


def _make_doc(db) -> KbDocumentModel:
    doc = KbDocumentModel(
        title=f"原子索引测试-{uuid4().hex[:8]}",
        kb_type="policy",
        file_type="text",
        visibility="PUBLIC",
        status="PUBLISHED",
        parse_status="done",
        index_status="pending",
        raw_content="第一段。社保补贴政策适用于就业困难人员。\n\n第二段。申请需提交身份证与社保缴费证明。",
        chunk_count=0,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_reindex_failure_keeps_old_live_chunks():
    principal = Principal("user", 1, "admin_local", "admin", None)
    with SessionLocal() as db:
        doc = _make_doc(db)
        doc_id = doc.id
        svc = KnowledgeBaseService(db)
        mock_client = MagicMock()
        mock_client.embed_batch.side_effect = lambda texts: [_embedding() for _ in texts]
        mock_client.available = True

        with patch("app.services.kb_service.get_embedding_client", return_value=mock_client), \
             patch.object(KnowledgeBaseService, "_store_embedding", return_value=None), \
             patch("app.services.ai_usage_recorder.AiUsageRecorder.record_embedding_call"):
            svc._parse_and_index(doc, principal)

        doc = db.get(KbDocumentModel, doc_id)
        assert doc.index_status == "ready"
        assert doc.active_index_batch
        live_batch = doc.active_index_batch
        live_contents = {
            c.content for c in db.scalars(
                select(KbChunkModel).where(
                    KbChunkModel.document_id == doc_id,
                    KbChunkModel.index_batch_id == live_batch,
                )
            ).all()
        }
        assert any("社保补贴" in c for c in live_contents)

        mock_client.embed_batch.side_effect = RuntimeError("embed down")
        with patch("app.services.kb_service.get_embedding_client", return_value=mock_client), \
             patch.object(KnowledgeBaseService, "_store_embedding", return_value=None), \
             patch("app.services.ai_usage_recorder.AiUsageRecorder.record_embedding_call"):
            svc._parse_and_index(doc, principal)

        doc = db.get(KbDocumentModel, doc_id)
        assert doc.index_status == "failed"
        assert doc.active_index_batch == live_batch
        assert doc.parse_status == "done"
        still_live = list(db.scalars(
            select(KbChunkModel).where(
                KbChunkModel.document_id == doc_id,
                KbChunkModel.index_batch_id == live_batch,
            )
        ).all())
        assert {c.content for c in still_live} == live_contents
        other = list(db.scalars(
            select(KbChunkModel).where(
                KbChunkModel.document_id == doc_id,
                KbChunkModel.index_batch_id != live_batch,
            )
        ).all())
        assert other == []


def test_reindex_success_switches_without_duplicate_chunks():
    principal = Principal("user", 1, "admin_local", "admin", None)
    with SessionLocal() as db:
        doc = _make_doc(db)
        doc_id = doc.id
        svc = KnowledgeBaseService(db)
        mock_client = MagicMock()
        mock_client.embed_batch.side_effect = lambda texts: [_embedding() for _ in texts]
        mock_client.available = True

        with patch("app.services.kb_service.get_embedding_client", return_value=mock_client), \
             patch.object(KnowledgeBaseService, "_store_embedding", return_value=None), \
             patch("app.services.ai_usage_recorder.AiUsageRecorder.record_embedding_call"):
            svc._parse_and_index(doc, principal)

        doc = db.get(KbDocumentModel, doc_id)
        first_batch = doc.active_index_batch
        assert first_batch

        doc.raw_content = "更新版正文。新的补贴条款只适用于本市户籍就业困难人员。"
        db.commit()

        with patch("app.services.kb_service.get_embedding_client", return_value=mock_client), \
             patch.object(KnowledgeBaseService, "_store_embedding", return_value=None), \
             patch("app.services.ai_usage_recorder.AiUsageRecorder.record_embedding_call"):
            svc._parse_and_index(doc, principal)

        doc = db.get(KbDocumentModel, doc_id)
        assert doc.index_status == "ready"
        assert doc.active_index_batch != first_batch
        all_chunks = list(db.scalars(
            select(KbChunkModel).where(KbChunkModel.document_id == doc_id)
        ).all())
        assert all(c.index_batch_id == doc.active_index_batch for c in all_chunks)
        assert len(all_chunks) == doc.chunk_count
        assert any("更新版正文" in c.content for c in all_chunks)
        assert not any("第一段" in c.content for c in all_chunks)
