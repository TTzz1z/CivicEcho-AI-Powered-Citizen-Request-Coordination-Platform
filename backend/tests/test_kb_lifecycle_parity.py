from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.authorization import Principal
from app.database import SessionLocal
from app.errors import BusinessError, PermissionDenied
from app.models import KbDocumentModel
from app.services.kb_service import KnowledgeBaseService


def test_policy_dates_align_between_search_browsing_and_download(persisted_kb_admin):
    keyword = "policy-date-" + uuid4().hex
    now = datetime.now(timezone.utc)
    citizen = Principal("user", 1, "citizen-fixture", "citizen", None)
    with SessionLocal() as db:
        docs = [
            KbDocumentModel(title=keyword + " expired", status="PUBLISHED", visibility="PUBLIC",
                            expires_at=now - timedelta(hours=1)),
            KbDocumentModel(title=keyword + " future", status="PUBLISHED", visibility="PUBLIC",
                            effective_at=now + timedelta(hours=1)),
            KbDocumentModel(title=keyword + " withdrawn", status="WITHDRAWN", visibility="PUBLIC"),
            KbDocumentModel(title=keyword + " current", status="PUBLISHED", visibility="PUBLIC"),
        ]
        db.add_all(docs)
        db.flush()
        try:
            service = KnowledgeBaseService(db)
            rows, total = service.list_documents(citizen, keyword=keyword)
            assert total == 1 and [row.id for row in rows] == [docs[-1].id]
            assert service.get_document(docs[-1].id, citizen) is docs[-1]
            assert service.list_chunks(docs[-1].id, citizen) == ([], 0)
            with pytest.raises(BusinessError, match="没有可下载"):
                service.download_file(docs[-1].id, citizen)
            for doc in docs[:-1]:
                for read in (service.get_document, service.list_chunks, service.download_file):
                    with pytest.raises(PermissionDenied):
                        read(doc.id, citizen)
                assert service.get_document(doc.id, persisted_kb_admin) is doc
        finally:
            db.rollback()
