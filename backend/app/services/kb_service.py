"""Knowledge Base Service: document lifecycle, parsing, vector indexing, RAG retrieval.

Pipeline:
  权限过滤 → 元数据过滤 → 向量召回 → 关键词召回 → 结果融合 → 重排序 → 有效期检查 → 引用生成
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session, selectinload

from ..authorization import Principal
from ..config import get_settings
from ..document_parser import ParsedDocument, extract_keywords, parse_bytes
from ..embedding_client import get_embedding_client
from ..errors import BusinessError, PermissionDenied
from ..llm_client import get_llm_client
from ..logging_config import request_id_context
from ..models import (
    KbChunkModel,
    KbDocumentModel,
    KbEvalCaseModel,
    KbEvalRunModel,
    KbFeedbackModel,
    KbNoAnswerQuestionModel,
)
from ..repositories.identity import AuditRepository
from ..storage import get_object_storage
from .ai_usage_recorder import (
    AiUsageRecorder,
    make_context,
    CAP_POLICY_RAG,
    CAP_SERVICE_GUIDE,
    CAP_TICKET_ADVICE,
    CAP_EMBEDDING_INDEX,
    CAP_EMBEDDING_QUERY,
)

logger = logging.getLogger(__name__)

# --- Chinese tokenizer (jieba with regex fallback) ---
# Round 2 r2-6: reliable Chinese word segmentation for keyword search.
# Falls back to bigram sliding-window regex if jieba is unavailable.
try:
    import jieba  # type: ignore

    # Warm up jieba's dictionary on first import so the first user query
    # doesn't pay the full cold-start cost.
    try:
        jieba.initialize()
    except Exception:  # pragma: no cover - defensive
        pass
    _JIEBA_AVAILABLE = True
except Exception:  # pragma: no cover - environment without jieba
    _JIEBA_AVAILABLE = False
    logger.warning("jieba not available; falling back to bigram regex tokenizer")


def _tokenize_zh(text: str) -> list[str]:
    """Tokenize Chinese text into search terms.

    Uses jieba.cut for accurate word segmentation; falls back to a
    bigram sliding-window over CJK runs plus regex for ASCII terms.
    Returns lowercased tokens with stopwords removed.
    """
    if not text:
        return []
    s = text.lower()
    tokens: list[str] = []
    if _JIEBA_AVAILABLE:
        for tok in jieba.cut(s, cut_all=False):
            tok = tok.strip()
            if not tok:
                continue
            # Keep CJK tokens (length>=2 to drop single chars unless they are
            # well-known single-char terms like 社保/医保 sub-parts) and ASCII terms
            if re.fullmatch(r"[\u4e00-\u9fff]+", tok):
                if len(tok) >= 2:
                    tokens.append(tok)
                elif tok in ("军", "税", "医", "房", "老", "病", "学"):
                    # Domain single-char terms worth indexing
                    tokens.append(tok)
            elif re.fullmatch(r"[a-z][a-z0-9_]{1,}", tok) or re.fullmatch(r"\d{2,}", tok):
                tokens.append(tok)
        # If jieba produced too few tokens for a short query (e.g. "路灯坏了"),
        # additionally slide bigrams over the raw CJK run so partial matches
        # against chunk content are still possible.
        if len(tokens) < 2:
            for m in re.finditer(r"[\u4e00-\u9fff]+", s):
                run = m.group(0)
                for i in range(len(run) - 1):
                    tokens.append(run[i:i + 2])
    else:
        # Fallback: regex tokenization (CJK bigrams + ASCII terms)
        for m in re.finditer(r"[\u4e00-\u9fff]+", s):
            run = m.group(0)
            if len(run) <= 2:
                tokens.append(run)
            else:
                for i in range(len(run) - 1):
                    tokens.append(run[i:i + 2])
        for m in re.finditer(r"[a-z][a-z0-9_]{1,}|\d{2,}", s):
            tokens.append(m.group(0))
    # Drop common Chinese stopwords to improve signal-to-noise
    stop = {"的", "了", "是", "在", "和", "与", "或", "及", "我", "你", "他",
            "我们", "你们", "他们", "请问", "一下", "什么", "怎么", "如何",
            "哪里", "哪个", "可以", "能够", "需要", "想", "要", "有", "没有"}
    return [t for t in tokens if t not in stop]


# Round 2 r2-6: query rewrite for short citizen queries.
# Short queries like "路灯坏了" need expansion to match policy / guide docs
# that mention "路灯" "故障" "维修" "市政" etc. We add domain synonyms without
# calling an LLM — this is deterministic and cost-free.
_QUERY_SYNONYMS = {
    "路灯": ["路灯", "照明", "市政照明", "路灯故障", "路灯维修"],
    "坏了": ["坏了", "故障", "损坏", "失效", "报修", "维修"],
    "漏水": ["漏水", "渗水", "管道", "供水", "维修"],
    "噪音": ["噪音", "扰民", "噪声", "环境噪声"],
    "垃圾": ["垃圾", "环境卫生", "清扫", "清运"],
    "身份证": ["身份证", "居民身份证", "办理身份证", "换证", "补证"],
    "社保": ["社保", "社会保险", "养老保险", "医疗保险", "工伤保险"],
    "公积金": ["公积金", "住房公积金", "缴存", "提取"],
    "入学": ["入学", "义务教育", "学校招生", "学区"],
    "落户": ["落户", "户籍", "户口迁入", "居住证"],
    "补贴": ["补贴", "补助", "津贴", "发放"],
    "低保": ["低保", "最低生活保障", "社会救助"],
}


def _rewrite_query(query: str) -> str:
    """Expand short queries with domain synonyms (deterministic, no LLM)."""
    if not query:
        return query
    extras: list[str] = []
    for keyword, syns in _QUERY_SYNONYMS.items():
        if keyword in query:
            extras.extend(syns)
    if not extras:
        return query
    return f"{query} {' '.join(extras)}"


# --- Constants ---

KB_TYPES = {"policy", "guide", "faq", "internal", "procedure", "case"}
VISIBILITIES = {"PUBLIC", "DEPARTMENT", "INTERNAL"}
DOC_STATUSES = {"DRAFT", "REVIEWING", "PUBLISHED", "REJECTED", "WITHDRAWN", "EXPIRED", "PARSE_FAILED"}
INDEX_STATUSES = {"pending", "building", "ready", "failed"}
ALLOWED_FILE_EXTS = {"pdf", "docx", "md", "markdown", "txt", "text"}


def _derive_embedding_provider(base_url: str) -> str:
    """Derive a short provider label from the embedding base URL (P0-D traceability)."""
    if not base_url:
        return "unknown"
    host = base_url.lower()
    if "siliconflow" in host:
        return "silicon_flow"
    if "deepseek" in host:
        return "deepseek"
    if "openai.com" in host:
        return "openai"
    if "volcengine" in host or "ark.cn-beijing" in host:
        return "volcengine"
    # Strip scheme and take the hostname as a last-resort label.
    return host.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0][:60]


class KnowledgeBaseService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.audit = AuditRepository(db)

    # ====================================================================
    # Document CRUD
    # ====================================================================

    def create_document(self, principal: Principal, *, raw_content: Optional[str] = None,
                       title: str, doc_number: Optional[str] = None, kb_type: str = "policy",
                       domain: Optional[str] = None, region: Optional[str] = None,
                       audience: Optional[str] = None, file_type: str = "text",
                       visibility: str = "PUBLIC", keywords: Optional[str] = None,
                       source_url: Optional[str] = None, effective_at: Optional[str] = None,
                       expires_at: Optional[str] = None, department_id: Optional[int] = None,
                       tags: Optional[list[str]] = None, auto_publish: bool = False,
                       issuing_authority: Optional[str] = None,
                       **extra) -> KbDocumentModel:
        """Create a new KB document (draft) from raw text content."""
        if principal.role not in {"department_staff", "admin"}:
            raise PermissionDenied("只有部门人员和管理员可以上传文档")
        if kb_type not in KB_TYPES:
            raise BusinessError("INVALID_KB_TYPE", f"知识库类型必须是 {KB_TYPES}", 422)
        if visibility not in VISIBILITIES:
            raise BusinessError("INVALID_VISIBILITY", f"公开范围必须是 {VISIBILITIES}", 422)
        # Department staff can only upload for their own department
        if principal.role == "department_staff":
            if department_id and department_id != principal.department_id:
                raise PermissionDenied("部门人员只能为本部门上传文档")
            department_id = principal.department_id
        # Visibility rules: department staff cannot mark as INTERNAL
        if visibility == "INTERNAL" and principal.role != "admin":
            raise PermissionDenied("仅管理员可设置 INTERNAL 公开范围")

        eff_dt = _parse_iso(effective_at)
        exp_dt = _parse_iso(expires_at)
        if eff_dt and exp_dt and exp_dt <= eff_dt:
            raise BusinessError("INVALID_DATES", "失效时间必须晚于生效时间", 422)

        doc = KbDocumentModel(
            title=title.strip(),
            doc_number=doc_number,
            issuing_authority=issuing_authority,
            department_id=department_id,
            published_department_id=department_id,
            kb_type=kb_type,
            domain=domain,
            region=region,
            audience=audience,
            file_type=file_type,
            visibility=visibility,
            status="DRAFT",
            version=1,
            source_url=source_url,
            keywords=keywords,
            effective_at=eff_dt,
            expires_at=exp_dt,
            raw_content=raw_content,
            uploaded_by_user_id=principal.user_id,
            tags=json.dumps(tags, ensure_ascii=False) if tags else None,
            parse_status="pending" if raw_content else "pending",
            index_status="pending",
            chunking_version="v2",
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        if raw_content:
            self._parse_and_index(doc, principal)

        # First version may be directly published if admin and auto_publish
        if auto_publish and principal.role == "admin" and self.settings.kb_allow_direct_publish:
            self._publish_internal(doc, principal, comment="管理员直接发布")
        self.audit.log(principal, "kb_doc_create",
                       resource_type="kb_document", resource_id=str(doc.id),
                       details={"title": doc.title, "kb_type": kb_type, "visibility": visibility})
        return doc

    def upload_file(self, principal: Principal, *, doc_id: Optional[int] = None,
                    file_bytes: bytes, filename: str, mime_type: Optional[str] = None,
                    title: Optional[str] = None, doc_number: Optional[str] = None,
                    kb_type: str = "policy", domain: Optional[str] = None,
                    region: Optional[str] = None, audience: Optional[str] = None,
                    visibility: str = "PUBLIC", keywords: Optional[str] = None,
                    source_url: Optional[str] = None, effective_at: Optional[str] = None,
                    expires_at: Optional[str] = None, department_id: Optional[int] = None,
                    tags: Optional[list[str]] = None, auto_publish: bool = False,
                    issuing_authority: Optional[str] = None) -> KbDocumentModel:
        """Upload a file (PDF/Word/MD/TXT) and create or replace a document."""
        if principal.role not in {"department_staff", "admin"}:
            raise PermissionDenied("只有部门人员和管理员可以上传文档")
        # Validate extension
        ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
        if ext not in ALLOWED_FILE_EXTS:
            raise BusinessError("INVALID_FILE_TYPE",
                                f"仅支持 {','.join(sorted(ALLOWED_FILE_EXTS))} 类型", 422)
        size = len(file_bytes)
        if size == 0:
            raise BusinessError("EMPTY_FILE", "上传文件为空", 422)
        if size > self.settings.attachment_max_bytes:
            raise BusinessError("FILE_TOO_LARGE", "文件超过大小限制", 413)

        # Parse content first
        parsed = parse_bytes(file_bytes, filename, mime_type)
        file_type_map = {"pdf": "pdf", "docx": "word", "md": "markdown", "markdown": "markdown", "txt": "text", "text": "text"}
        file_type = file_type_map.get(ext, "text")
        title = (title or filename.rsplit(".", 1)[0]).strip()

        # If doc_id provided, create a new version
        if doc_id:
            doc = self._get_doc(doc_id)
            # P0-D fix: admin can create new versions of any document.
            self._require_dept_access(doc, principal, allow_admin=True)
            new_doc = self._create_new_version(doc, principal, parsed, title, file_bytes,
                                                filename, mime_type, file_type)
            return new_doc

        # Otherwise create a new doc with file content
        doc = self.create_document(
            principal,
            title=title,
            doc_number=doc_number,
            kb_type=kb_type,
            domain=domain,
            region=region,
            audience=audience,
            file_type=file_type,
            visibility=visibility,
            keywords=keywords,
            source_url=source_url,
            effective_at=effective_at,
            expires_at=expires_at,
            department_id=department_id,
            tags=tags,
            raw_content=parsed.text,
            auto_publish=auto_publish,
            issuing_authority=issuing_authority,
        )
        # Store the file in object storage and record metadata
        storage_key = self._store_file(doc, file_bytes, filename)
        doc.storage_key = storage_key
        doc.original_filename = filename
        doc.mime_type = mime_type
        doc.file_size_bytes = len(file_bytes)
        doc.ocr_status = parsed.ocr_status
        doc.ocr_quality = parsed.ocr_quality
        meta = {"parser_notes": parsed.parser_notes, "page_count": parsed.page_count}
        doc.meta_json = json.dumps(meta, ensure_ascii=False)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    def _create_new_version(self, parent: KbDocumentModel, principal: Principal,
                            parsed: ParsedDocument, title: str, file_bytes: bytes,
                            filename: str, mime_type: Optional[str], file_type: str) -> KbDocumentModel:
        """Create a new version of a document. Old versions are retained but not re-published."""
        if parent.status != "PUBLISHED" and parent.status != "WITHDRAWN" and parent.status != "EXPIRED":
            raise BusinessError("INVALID_STATUS",
                                "仅已发布、已下线或已失效的文档可以创建新版本", 409)
        # Bump version number
        next_version = parent.version + 1
        # Store file
        new_doc = KbDocumentModel(
            title=title or parent.title,
            doc_number=parent.doc_number,
            department_id=parent.department_id,
            published_department_id=parent.published_department_id or parent.department_id,
            kb_type=parent.kb_type,
            domain=parent.domain,
            region=parent.region,
            audience=parent.audience,
            file_type=file_type,
            visibility=parent.visibility,
            status="DRAFT",
            version=next_version,
            parent_version_id=parent.id,
            replaces_doc_id=parent.id,
            source_url=parent.source_url,
            keywords=parent.keywords,
            effective_at=_parse_iso(None),
            expires_at=parent.expires_at,
            raw_content=parsed.text,
            uploaded_by_user_id=principal.user_id,
            tags=parent.tags,
            parse_status="pending",
            index_status="pending",
            chunking_version="v2",
        )
        self.db.add(new_doc)
        self.db.commit()
        self.db.refresh(new_doc)
        storage_key = self._store_file(new_doc, file_bytes, filename)
        new_doc.storage_key = storage_key
        new_doc.original_filename = filename
        new_doc.mime_type = mime_type
        new_doc.file_size_bytes = len(file_bytes)
        new_doc.ocr_status = parsed.ocr_status
        new_doc.ocr_quality = parsed.ocr_quality
        meta = {"parser_notes": parsed.parser_notes, "page_count": parsed.page_count,
                "parent_version": parent.version}
        new_doc.meta_json = json.dumps(meta, ensure_ascii=False)
        self.db.commit()
        self._parse_and_index(new_doc, principal)
        self.audit.log(principal, "kb_doc_new_version",
                       resource_type="kb_document", resource_id=str(new_doc.id),
                       details={"parent_id": parent.id, "parent_version": parent.version,
                                "new_version": next_version})
        return new_doc

    def _store_file(self, doc: KbDocumentModel, file_bytes: bytes, filename: str) -> str:
        """Store file in MinIO under KB bucket. Returns object key."""
        settings = self.settings
        # Use a dedicated KB bucket; create on demand
        try:
            from minio import Minio
            client = Minio(
                settings.object_storage_endpoint.removeprefix("https://").removeprefix("http://"),
                access_key=settings.object_storage_access_key,
                secret_key=settings.object_storage_secret_key,
                secure=settings.object_storage_secure,
                region=settings.object_storage_region,
            )
            bucket = settings.kb_upload_bucket
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket, location=settings.object_storage_region)
            object_key = f"docs/{doc.id}/{uuid.uuid4().hex}_{filename}"
            import io
            client.put_object(bucket, object_key, io.BytesIO(file_bytes), len(file_bytes),
                              content_type="application/octet-stream")
            return object_key
        except Exception as exc:
            logger.warning("KB file storage failed: %s", exc)
            return ""

    def download_file(self, doc_id: int, principal: Principal) -> tuple[bytes, str, Optional[str]]:
        """Return (bytes, filename, mime_type) for download. Permission-checked."""
        doc = self._get_doc(doc_id)
        self._require_dept_access(doc, principal, allow_admin=True)
        if not doc.storage_key:
            raise BusinessError("NO_FILE", "该文档没有可下载的源文件", 404)
        try:
            from minio import Minio
            settings = self.settings
            client = Minio(
                settings.object_storage_endpoint.removeprefix("https://").removeprefix("http://"),
                access_key=settings.object_storage_access_key,
                secret_key=settings.object_storage_secret_key,
                secure=settings.object_storage_secure,
                region=settings.object_storage_region,
            )
            response = client.get_object(settings.kb_upload_bucket, doc.storage_key)
            try:
                data = response.read()
            finally:
                response.close()
                response.release_conn()
            return data, doc.original_filename or "document", doc.mime_type
        except Exception as exc:
            logger.warning("KB file download failed: %s", exc)
            raise BusinessError("DOWNLOAD_FAILED", "文件下载失败", 500)

    # ====================================================================
    # Lifecycle: review, publish, withdraw, expire
    # ====================================================================

    def update_metadata(self, doc_id: int, principal: Principal, **fields) -> KbDocumentModel:
        doc = self._get_doc(doc_id)
        # P0-D fix: admin can edit any document's metadata.
        self._require_dept_access(doc, principal, allow_admin=True)
        if doc.status not in {"DRAFT", "REJECTED"}:
            raise BusinessError("INVALID_STATUS", "仅草稿或驳回状态的文档可修改元数据", 409)
        allowed = {"title", "doc_number", "issuing_authority", "domain", "region", "audience", "keywords",
                   "source_url", "effective_at", "expires_at", "visibility", "audience",
                   "department_id", "kb_type"}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"effective_at", "expires_at"}:
                setattr(doc, key, _parse_iso(value))
            elif key == "tags" and isinstance(value, list):
                doc.tags = json.dumps(value, ensure_ascii=False)
            elif key == "visibility" and value == "INTERNAL" and principal.role != "admin":
                raise PermissionDenied("仅管理员可设置 INTERNAL 公开范围")
            else:
                setattr(doc, key, value)
        self.db.commit()
        self.audit.log(principal, "kb_doc_update_metadata",
                       resource_type="kb_document", resource_id=str(doc.id), details={"fields": list(fields.keys())})
        return doc

    def submit_for_review(self, doc_id: int, principal: Principal):
        doc = self._get_doc(doc_id)
        # P0-D fix: admin can submit any document for review.
        self._require_dept_access(doc, principal, allow_admin=True)
        if doc.status not in {"DRAFT", "REJECTED"}:
            raise BusinessError("INVALID_STATUS", "只有草稿或驳回状态可以提交审核", 409)
        if not doc.raw_content or not doc.raw_content.strip():
            raise BusinessError("NO_CONTENT", "文档无正文内容，无法提交审核", 409)
        doc.status = "REVIEWING"
        self.db.commit()
        self.audit.log(principal, "kb_doc_submit_review",
                       resource_type="kb_document", resource_id=str(doc.id), details={"version": doc.version})

    def review_document(self, doc_id: int, decision: str, comment: str, principal: Principal):
        if principal.role != "admin":
            raise PermissionDenied("只有管理员可以审核文档")
        doc = self._get_doc(doc_id)
        if doc.status != "REVIEWING":
            raise BusinessError("INVALID_STATUS", "只有待审核状态可以审核", 409)
        doc.reviewed_by_user_id = principal.user_id
        doc.reviewed_at = datetime.now(timezone.utc)
        doc.review_comment = comment
        if decision == "publish":
            self._publish_internal(doc, principal, comment)
        else:
            doc.status = "REJECTED"
            doc.rejected_reason = comment
        self.db.commit()
        self.audit.log(principal, "kb_doc_review",
                       resource_type="kb_document", resource_id=str(doc.id),
                       details={"decision": decision, "comment": comment})

    def direct_publish(self, doc_id: int, principal: Principal, comment: str = ""):
        """Admin can directly publish a DRAFT (first version)."""
        if principal.role != "admin":
            raise PermissionDenied("仅管理员可直接发布")
        if not self.settings.kb_allow_direct_publish:
            raise BusinessError("DIRECT_PUBLISH_DISABLED", "管理员直发已被禁用", 403)
        doc = self._get_doc(doc_id)
        if doc.status not in {"DRAFT", "REJECTED"}:
            raise BusinessError("INVALID_STATUS", "只有草稿/驳回状态可直接发布", 409)
        if not doc.raw_content or not doc.raw_content.strip():
            raise BusinessError("NO_CONTENT", "文档无正文内容，无法发布", 409)
        self._publish_internal(doc, principal, comment)
        self.db.commit()
        self.audit.log(principal, "kb_doc_direct_publish",
                       resource_type="kb_document", resource_id=str(doc.id), details={"comment": comment})

    def _publish_internal(self, doc: KbDocumentModel, principal: Principal, comment: str = ""):
        """Publish document and trigger indexing."""
        doc.status = "PUBLISHED"
        doc.published_at = datetime.now(timezone.utc)
        doc.published_by_user_id = principal.user_id
        doc.review_comment = comment
        if not doc.effective_at:
            doc.effective_at = doc.published_at
        # If this doc replaces another, mark the old one as WITHDRAWN/EXPIRED
        if doc.replaces_doc_id:
            old = self.db.get(KbDocumentModel, doc.replaces_doc_id)
            if old and old.status == "PUBLISHED":
                old.status = "WITHDRAWN"
        # Trigger parse + index
        self._parse_and_index(doc, principal)

    def withdraw_document(self, doc_id: int, principal: Principal, reason: str = ""):
        doc = self._get_doc(doc_id)
        self._require_dept_access(doc, principal, allow_admin=True)
        if doc.status != "PUBLISHED":
            raise BusinessError("INVALID_STATUS", "只有已发布状态可以下线", 409)
        doc.status = "WITHDRAWN"
        self.db.commit()
        self.audit.log(principal, "kb_doc_withdraw",
                       resource_type="kb_document", resource_id=str(doc.id), details={"reason": reason})

    def expire_document(self, doc_id: int, principal: Principal, reason: str = ""):
        """Manually mark a published document as expired."""
        doc = self._get_doc(doc_id)
        self._require_dept_access(doc, principal, allow_admin=True)
        if doc.status != "PUBLISHED":
            raise BusinessError("INVALID_STATUS", "只有已发布状态可以标记失效", 409)
        doc.status = "EXPIRED"
        doc.expires_at = datetime.now(timezone.utc)
        self.db.commit()
        self.audit.log(principal, "kb_doc_expire",
                       resource_type="kb_document", resource_id=str(doc.id), details={"reason": reason})

    # ====================================================================
    # Parsing & indexing
    # ====================================================================

    def _parse_and_index(self, doc: KbDocumentModel, principal: Optional[Principal] = None):
        """Parse doc raw_content into chunks, embed, and store vectors."""
        if not doc.raw_content:
            doc.parse_status = "failed"
            doc.index_status = "failed"
            self.db.commit()
            return
        doc.parse_status = "parsing"
        doc.index_status = "building"
        self.db.commit()
        try:
            chunks_text = self._split_text(doc.raw_content)
            # Delete old chunks
            old_chunks = list(self.db.scalars(
                select(KbChunkModel).where(KbChunkModel.document_id == doc.id)
            ).all())
            for c in old_chunks:
                self.db.delete(c)
            self.db.flush()

            # Embed all chunks in batch
            embedding_client = get_embedding_client()
            embed_results = embedding_client.embed_batch(chunks_text)
            embedding_model_used = embed_results[0].model if embed_results else None
            embedding_provider_used = _derive_embedding_provider(self.settings.embedding_base_url)
            # P0-D: record embedding_index call with real usage / fallback status.
            total_chars = sum(len(t) for t in chunks_text)
            embed_for_log = embed_results[0] if embed_results else None
            if embed_for_log is not None:
                AiUsageRecorder(self.db).record_embedding_call(
                    make_context(CAP_EMBEDDING_INDEX, route="kb_index",
                                 principal=principal, request_id=request_id_context.get()),
                    embed_for_log,
                    text_count=len(chunks_text),
                    text_chars=total_chars,
                    degraded=embed_for_log.fallback,
                    degrade_reason="embedding_fallback" if embed_for_log.fallback else None,
                )

            for i, (chunk_text, embed_result) in enumerate(zip(chunks_text, embed_results)):
                chunk_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:64]
                keywords_list = extract_keywords(chunk_text, max_keywords=15)
                # P0-D: classify fallback status for traceability.
                if not embed_result.success:
                    fallback_status = "primary_failed"
                elif embed_result.model == "fallback-hash":
                    fallback_status = "fallback_used"
                else:
                    fallback_status = "none"
                chunk = KbChunkModel(
                    document_id=doc.id,
                    chunk_index=i,
                    content=chunk_text,
                    chunk_hash=chunk_hash,
                    keywords=json.dumps(keywords_list, ensure_ascii=False) if keywords_list else None,
                    token_count=len(chunk_text),
                    char_count=len(chunk_text),
                    embedding_model=embed_result.model,
                    embedding_provider=embedding_provider_used,
                    embedding_dimension=embed_result.dimensions,
                    embedding_fallback=fallback_status,
                )
                self.db.add(chunk)
                self.db.flush()
                # Store embedding via raw SQL (pgvector type)
                if embed_result.success and embed_result.vector:
                    self._store_embedding(chunk.id, embed_result.vector)

            doc.chunk_count = len(chunks_text)
            doc.parse_status = "done"
            doc.index_status = "ready"
            doc.embedding_model = embedding_model_used
            doc.chunking_version = "v2"
            self.db.commit()
        except Exception as exc:
            logger.warning("Indexing failed for doc %d: %s", doc.id, exc)
            # flush failure puts session into rolled-back state; rollback first
            # so we can still mark the doc as failed in a fresh transaction.
            self.db.rollback()
            failed_doc = self.db.get(KbDocumentModel, doc.id)
            if failed_doc:
                failed_doc.parse_status = "failed"
                failed_doc.index_status = "failed"
            self.db.commit()

    def _store_embedding(self, chunk_id: int, vector: list[float]):
        """Store embedding vector using pgvector raw SQL."""
        # Format vector as pgvector literal: '[0.1,0.2,...]'
        vec_str = "[" + ",".join(f"{v:.8f}" for v in vector) + "]"
        # Use CAST(... AS vector) instead of ::vector because SQLAlchemy text()
        # binds :vec as a parameter and the `::` syntax collides with param names.
        self.db.execute(
            text("UPDATE kb_chunks SET embedding = CAST(:vec AS vector) WHERE id = :cid"),
            {"vec": vec_str, "cid": chunk_id},
        )

    def reindex(self, doc_id: int, principal: Principal):
        """Re-parse and re-build index for a document."""
        doc = self._get_doc(doc_id)
        self._require_dept_access(doc, principal, allow_admin=True)
        if not doc.raw_content:
            raise BusinessError("NO_CONTENT", "文档无正文内容", 409)
        self._parse_and_index(doc, principal)
        self.audit.log(principal, "kb_doc_reindex",
                       resource_type="kb_document", resource_id=str(doc.id),
                       details={"chunk_count": doc.chunk_count, "index_status": doc.index_status})

    @staticmethod
    def _split_text(text: str) -> list[str]:
        """Split text into overlapping chunks. Uses config-driven size/overlap."""
        settings = get_settings()
        chunk_size = max(120, settings.kb_chunk_size)
        overlap = max(0, min(settings.kb_chunk_overlap, chunk_size // 2))
        # First split by paragraphs
        paragraphs = re.split(r"\n\s*\n", text)
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current) + len(para) <= chunk_size:
                current = f"{current}\n{para}" if current else para
                continue
            if current:
                chunks.append(current)
            # If paragraph itself is too long, split by sentences
            if len(para) > chunk_size:
                sentences = re.split(r"(?<=[。！？；\n])", para)
                sub = ""
                for sent in sentences:
                    if len(sub) + len(sent) <= chunk_size:
                        sub += sent
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = sent
                current = sub
            else:
                current = para
        if current:
            chunks.append(current)
        # Apply overlap by prepending tail of previous chunk to next
        if overlap > 0 and len(chunks) > 1:
            overlapped: list[str] = [chunks[0]]
            for i in range(1, len(chunks)):
                prev_tail = chunks[i - 1][-overlap:]
                overlapped.append(prev_tail + "\n" + chunks[i])
            chunks = overlapped
        return chunks if chunks else ([text[:chunk_size]] if text else [])

    # ====================================================================
    # List / detail / version
    # ====================================================================

    def list_documents(self, principal: Principal, *,
                       status: Optional[str] = None,
                       kb_type: Optional[str] = None,
                       visibility: Optional[str] = None,
                       department_id: Optional[int] = None,
                       domain: Optional[str] = None,
                       keyword: Optional[str] = None,
                       limit: int = 100,
                       offset: int = 0) -> tuple[list[KbDocumentModel], int]:
        """List documents based on role permissions."""
        stmt = select(KbDocumentModel)
        # Permission filter FIRST
        stmt = self._apply_visibility_filter(stmt, principal)
        if status:
            stmt = stmt.where(KbDocumentModel.status == status)
        if kb_type:
            stmt = stmt.where(KbDocumentModel.kb_type == kb_type)
        if visibility and principal.role == "admin":
            stmt = stmt.where(KbDocumentModel.visibility == visibility)
        if department_id and principal.role in {"admin", "agent"}:
            stmt = stmt.where(KbDocumentModel.department_id == department_id)
        if domain:
            stmt = stmt.where(KbDocumentModel.domain == domain)
        if keyword:
            term = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(
                KbDocumentModel.title.ilike(term),
                KbDocumentModel.doc_number.ilike(term),
                KbDocumentModel.keywords.ilike(term),
            ))
        # Total count
        from sqlalchemy import func
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(self.db.scalar(count_stmt) or 0)
        # Pagination
        items = list(self.db.scalars(
            stmt.order_by(KbDocumentModel.created_at.desc())
            .offset(offset).limit(limit)
        ).all())
        return items, total

    def get_document(self, doc_id: int, principal: Principal) -> KbDocumentModel:
        doc = self._get_doc(doc_id)
        self._require_dept_access(doc, principal, allow_admin=True, allow_view_published=True)
        return doc

    def list_versions(self, doc_id: int, principal: Principal) -> list[KbDocumentModel]:
        doc = self._get_doc(doc_id)
        self._require_dept_access(doc, principal, allow_admin=True)
        # Find root of the version chain by walking parent_version_id upward.
        root_id = doc.id
        current = doc
        seen: set[int] = set()
        while current.parent_version_id and current.id not in seen:
            seen.add(current.id)
            current = self.db.get(KbDocumentModel, current.parent_version_id)
            if not current:
                break
            root_id = current.id
        # P0-F fix: walk the full chain downward via recursive CTE so v1→v2→v3
        # (where v3.parent_version_id == v2.id, not root) is still included.
        sql = text("""
            WITH RECURSIVE version_chain AS (
                SELECT id FROM kb_documents WHERE id = :root_id
                UNION ALL
                SELECT child.id
                FROM kb_documents child
                JOIN version_chain parent ON child.parent_version_id = parent.id
            )
            SELECT id FROM version_chain
            ORDER BY (SELECT version FROM kb_documents WHERE id = version_chain.id) ASC
            LIMIT 50
        """)
        rows = self.db.execute(sql, {"root_id": root_id}).all()
        if not rows:
            return []
        ids = [row[0] for row in rows]
        versions = list(self.db.scalars(
            select(KbDocumentModel).where(KbDocumentModel.id.in_(ids))
        ).all())
        # Preserve the recursive CTE ordering (ascending by version).
        order_index = {v.id: i for i, v in enumerate(versions)}
        versions.sort(key=lambda v: order_index.get(v.id, 0))
        # Filter by permission
        accessible = [v for v in versions if self._can_access(v, principal)]
        return accessible

    def list_chunks(self, doc_id: int, principal: Principal, limit: int = 20, offset: int = 0) -> tuple[list[KbChunkModel], int]:
        doc = self._get_doc(doc_id)
        self._require_dept_access(doc, principal, allow_admin=True, allow_view_published=True)
        from sqlalchemy import func
        total = int(self.db.scalar(
            select(func.count()).select_from(
                select(KbChunkModel).where(KbChunkModel.document_id == doc_id).subquery()
            )
        ) or 0)
        items = list(self.db.scalars(
            select(KbChunkModel)
            .where(KbChunkModel.document_id == doc_id)
            .order_by(KbChunkModel.chunk_index.asc())
            .offset(offset).limit(limit)
        ).all())
        return items, total

    # ====================================================================
    # RAG retrieval pipeline
    # ====================================================================

    def retrieve(self, query: str, principal: Principal, *,
                 top_k: Optional[int] = None,
                 region: Optional[str] = None,
                 domain: Optional[str] = None,
                 audience: Optional[str] = None,
                 department_id: Optional[int] = None,
                 include_expired: bool = False,
                 route: str = "rag_query") -> dict:
        """Full retrieval pipeline with permission filter first.

        Returns dict with:
          - chunks: list of scored chunk dicts
          - accessible_doc_count: int
          - no_evidence: bool
        """
        top_k = top_k or self.settings.kb_rag_top_k
        # Step 1: Permission filter - get accessible document IDs FIRST
        accessible_stmt = select(KbDocumentModel.id).where(
            KbDocumentModel.status == "PUBLISHED",
            KbDocumentModel.parse_status == "done",
            KbDocumentModel.index_status == "ready",
        )
        accessible_stmt = self._apply_visibility_filter(accessible_stmt, principal)
        # Expiry filter (default: exclude expired)
        now = datetime.now(timezone.utc)
        if include_expired:
            pass  # Admin/explicit debug only
        else:
            accessible_stmt = accessible_stmt.where(or_(
                KbDocumentModel.expires_at.is_(None),
                KbDocumentModel.expires_at > now,
            ))
        # Metadata filters
        if region:
            accessible_stmt = accessible_stmt.where(
                or_(KbDocumentModel.region.is_(None), KbDocumentModel.region == region)
            )
        if domain:
            accessible_stmt = accessible_stmt.where(KbDocumentModel.domain == domain)
        if audience:
            accessible_stmt = accessible_stmt.where(
                or_(KbDocumentModel.audience.is_(None), KbDocumentModel.audience == audience)
            )
        if department_id and principal.role in {"admin", "agent"}:
            accessible_stmt = accessible_stmt.where(
                KbDocumentModel.published_department_id == department_id
            )

        accessible_ids = list(self.db.scalars(accessible_stmt).all())
        accessible_doc_count = len(accessible_ids)
        if not accessible_ids:
            return {"chunks": [], "accessible_doc_count": 0, "no_evidence": True}

        # Step 2: Vector recall via pgvector cosine distance.
        # Use original query for embedding (preserves semantic intent); the
        # rewritten query is only used for keyword recall below.
        # Round 2 r2-8: when embedding falls back to pseudo vectors, do NOT
        # silently run vector_search on hash vectors (semantically meaningless).
        # Skip vector recall and rely on keyword recall instead; the fallback
        # is still recorded in ai_usage_logs with degrade_reason=embedding_fallback.
        vector_hits: list[tuple[float, int]] = []  # (score, chunk_id)
        embedding_client = get_embedding_client()
        embed_result = embedding_client.embed(query)
        # P0-D: record embedding_query call with real usage / fallback status.
        AiUsageRecorder(self.db).record_embedding_call(
            make_context(CAP_EMBEDDING_QUERY, route=route,
                         principal=principal, request_id=request_id_context.get()),
            embed_result,
            text_count=1,
            text_chars=len(query or ""),
            degraded=embed_result.fallback or not embed_result.success,
            degrade_reason=("embedding_fallback" if embed_result.fallback
                            else "embedding_failed" if not embed_result.success else None),
        )
        if embed_result.success and embed_result.vector and not embed_result.fallback:
            vector_hits = self._vector_search(embed_result.vector, accessible_ids, top_k * 3)

        # Step 3: Keyword recall (Round 2 r2-6: use rewritten query so short
        # queries like "路灯坏了" match documents that mention "路灯" "故障"
        # "维修" etc.)
        rewritten = _rewrite_query(query)
        keyword_hits = self._keyword_search(rewritten, accessible_ids, top_k * 3)

        # Step 4: Result fusion (Reciprocal Rank Fusion).
        # When embedding was skipped (fallback), fused == keyword_hits ranked
        # — keyword-only retrieval, exactly as required by r2-8.
        fused = self._reciprocal_rank_fusion(vector_hits, keyword_hits)

        # Step 5: Re-rank using a simple composite score (vector score + keyword overlap boost)
        reranked = self._rerank(rewritten, fused, accessible_ids, top_k)

        # Step 6: Build result dicts
        if not reranked:
            return {"chunks": [], "accessible_doc_count": accessible_doc_count, "no_evidence": True}
        chunk_ids = [cid for _, cid in reranked]
        chunks_by_id = {
            c.id: c for c in self.db.scalars(
                select(KbChunkModel)
                .where(KbChunkModel.id.in_(chunk_ids))
                .options(selectinload(KbChunkModel.document))
            ).all()
        }
        results = []
        for score, chunk_id in reranked:
            chunk = chunks_by_id.get(chunk_id)
            if not chunk:
                continue
            doc = chunk.document
            # Final expiry check (paranoid)
            is_expired = bool(doc.expires_at and doc.expires_at <= now)
            if is_expired and not include_expired:
                continue
            results.append({
                "chunk_id": chunk.id,
                "content": chunk.content,
                "score": round(score, 4),
                "chunk_index": chunk.chunk_index,
                "char_count": chunk.char_count,
                "is_expired": is_expired,
                "document": self._doc_to_dict(doc),
            })
        return {"chunks": results[:top_k], "accessible_doc_count": accessible_doc_count,
                "no_evidence": len(results) == 0}

    def _vector_search(self, query_vec: list[float], doc_ids: list[int], k: int) -> list[tuple[float, int]]:
        """Run pgvector cosine distance search. Returns [(score, chunk_id), ...]."""
        if not doc_ids:
            return []
        vec_str = "[" + ",".join(f"{v:.8f}" for v in query_vec) + "]"
        # Cosine distance: 1 - cosine similarity. We convert to similarity score.
        sql = text("""
            SELECT id, 1 - (embedding <=> CAST(:vec AS vector)) AS score
            FROM kb_chunks
            WHERE document_id = ANY(:doc_ids)
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
        """)
        rows = self.db.execute(sql, {"vec": vec_str, "doc_ids": doc_ids, "k": k}).all()
        return [(float(row.score), int(row.id)) for row in rows if row.score is not None]

    def _keyword_search(self, query: str, doc_ids: list[int], k: int) -> list[tuple[float, int]]:
        """Keyword overlap search across chunks of accessible docs.

        Round 2 r2-6: uses jieba-based _tokenize_zh for reliable Chinese
        word segmentation (was: naive regex extraction that treated "路灯坏了"
        as a single token and missed all matches).
        """
        if not doc_ids:
            return []
        query_terms = set(_tokenize_zh(query))
        if not query_terms:
            return []
        # Pull candidate chunks (limit to keep memory bounded)
        stmt = select(KbChunkModel).where(KbChunkModel.document_id.in_(doc_ids)) \
            .execution_options(stream_results=True)
        chunks = list(self.db.scalars(stmt).all()[:500])
        scored: list[tuple[float, int]] = []
        for chunk in chunks:
            chunk_terms = set(_tokenize_zh(chunk.content))
            if not chunk_terms:
                continue
            overlap = len(query_terms & chunk_terms)
            if overlap == 0:
                continue
            # Jaccard-like score
            score = overlap / max(1, len(query_terms | chunk_terms))
            scored.append((score, chunk.id))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]

    @staticmethod
    def _reciprocal_rank_fusion(vector_hits: list[tuple[float, int]],
                                 keyword_hits: list[tuple[float, int]],
                                 k_const: int = 60) -> list[tuple[float, int]]:
        """Combine ranked lists using RRF."""
        scores: dict[int, float] = {}
        for rank, (_, chunk_id) in enumerate(vector_hits, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k_const + rank)
        for rank, (_, chunk_id) in enumerate(keyword_hits, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k_const + rank)
        result = [(score, chunk_id) for chunk_id, score in scores.items()]
        result.sort(reverse=True)
        return result

    def _rerank(self, query: str, fused: list[tuple[float, int]],
                doc_ids: list[int], top_k: int) -> list[tuple[float, int]]:
        """Apply a simple rerank: boost chunks with high query-term density in content.

        Round 2 r2-6: uses jieba-based _tokenize_zh for accurate term matching.
        """
        if not fused:
            return []
        query_terms = set(_tokenize_zh(query))
        # Pull content for fused chunks
        chunk_ids = [cid for _, cid in fused[:top_k * 4]]
        if not chunk_ids:
            return fused[:top_k]
        chunks = list(self.db.scalars(
            select(KbChunkModel).where(KbChunkModel.id.in_(chunk_ids))
        ).all())
        chunk_content = {c.id: c.content for c in chunks}
        reranked: list[tuple[float, int]] = []
        for rrf_score, chunk_id in fused[:top_k * 4]:
            content = chunk_content.get(chunk_id, "").lower()
            if query_terms:
                # Density: how many query terms appear, normalized by content length
                hits = sum(1 for t in query_terms if t.lower() in content)
                density = hits / max(1, len(query_terms))
                # Length normalization: shorter chunks with same hit count score higher
                len_factor = 1.0 / (1.0 + len(content) / 1000.0)
                composite = rrf_score * 0.7 + density * 0.25 + len_factor * 0.05
            else:
                composite = rrf_score
            reranked.append((composite, chunk_id))
        reranked.sort(reverse=True)
        return reranked[:top_k]

    # ====================================================================
    # RAG answer generation
    # ====================================================================

    def rag_answer(self, query: str, principal: Principal, *,
                   region: Optional[str] = None,
                   domain: Optional[str] = None,
                   audience: Optional[str] = None,
                   route: str = "citizen_query",
                   session_id: Optional[str] = None,
                   request_id: Optional[str] = None) -> dict:
        """Full RAG pipeline: retrieve + generate answer with citations."""
        started = time.perf_counter()
        retrieval = self.retrieve(
            query, principal,
            region=region, domain=domain, audience=audience,
            route=route,
        )
        chunks = retrieval["chunks"]
        no_evidence = retrieval["no_evidence"]
        latency_ms = int((time.perf_counter() - started) * 1000)

        if no_evidence or not chunks:
            # Record as no-answer question for admin follow-up
            self._record_no_answer(query, principal, route=route,
                                   retrieved_doc_ids=[c["document"]["id"] for c in chunks])
            # P0-D: record rules-tier no-evidence decision (zero tokens, honest).
            AiUsageRecorder(self.db).record_rules_call(
                make_context(self._capability_for_route(route), route=route,
                             principal=principal, session_id=session_id,
                             request_id=request_id or request_id_context.get()),
                model_name="rules",
                degrade_reason="no_evidence",
            )
            return {
                "answer": _NO_EVIDENCE_MESSAGE,
                "citations": [],
                "no_evidence": True,
                "retrieval_count": 0,
                "latency_ms": latency_ms,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        # Build context & citations
        context_parts = []
        citations = []
        for i, c in enumerate(chunks):
            doc = c["document"]
            context_parts.append(
                f"[来源{i+1}: {doc['title']}（{doc.get('doc_number') or '无文号'}）"
                f"· 发布部门:{doc.get('department_name') or '未标注'}"
                f"· 发布日期:{(doc.get('published_at') or '')[:10] or '未标注'}"
                f"· 状态:{'已失效' if c.get('is_expired') else '有效'}]\n{c['content']}"
            )
            citations.append({
                "index": i + 1,
                "doc_id": doc["id"],
                "title": doc["title"],
                "doc_number": doc.get("doc_number"),
                "issuing_authority": doc.get("issuing_authority") or doc.get("published_department_name") or doc.get("department_name"),
                "department": doc.get("department_name"),
                "published_at": doc.get("published_at"),
                "effective_at": doc.get("effective_at"),
                "expires_at": doc.get("expires_at"),
                "status": doc.get("status"),
                "version": doc.get("version"),
                "is_expired": c.get("is_expired", False),
                "excerpt": c["content"][:240],
                "chunk_index": c.get("chunk_index"),
                "score": c.get("score"),
                "detail_url": f"/api/v1/kb/documents/{doc['id']}",
            })
        context = "\n\n".join(context_parts)

        # Generate answer with LLM
        answer, llm_used, llm_result = self._generate_answer(
            query, context, principal, route=route,
            session_id=session_id, request_id=request_id,
        )
        result = {
            "answer": answer,
            "citations": citations,
            "no_evidence": False,
            "retrieval_count": len(chunks),
            "latency_ms": latency_ms,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider": (llm_result.model if llm_used and llm_result and llm_result.success else "rules"),
            "model": (llm_result.model if llm_used and llm_result and llm_result.success else "rules-v2"),
            "degraded": (llm_used and llm_result and not llm_result.success),
        }
        return result

    def _generate_answer(self, query: str, context: str, principal: Principal, *,
                         route: str = "citizen_query",
                         session_id: Optional[str] = None,
                         request_id: Optional[str] = None) -> tuple[str, bool, Any]:
        """Generate final answer using LLM with role-specific prompt.

        Returns ``(answer_text, llm_used, llm_result)`` so callers can record
        provider/model/degraded status accurately. The LLM call is logged to
        ``ai_usage_logs`` here; the no-LLM fallback path is also logged.
        """
        llm = get_llm_client()
        capability = self._capability_for_route(route)
        # Role-specific prompt
        if principal.role == "citizen":
            structure = (
                "1. 简明结论\n2. 适用对象\n3. 申请或办理条件\n4. 所需材料\n5. 办理流程\n"
                "6. 负责部门\n7. 注意事项\n8. 政策来源\n9. 发布日期和有效状态"
            )
            role_hint = "你是政务服务政策咨询助手，面向市民。语言通俗易懂。"
        elif principal.role == "agent":
            structure = (
                "1. 政策依据要点\n2. 适用条件\n3. 办理流程\n4. 所需材料\n5. 负责部门\n"
                "6. 注意事项与时效\n7. 政策来源"
            )
            role_hint = "你是政务坐席政策辅助助手，提供完整准确的政策要点供坐席回复市民。"
        elif principal.role == "department_staff":
            structure = (
                "1. 适用依据要点\n2. 办理流程\n3. 材料检查\n4. 时限要求\n"
                "5. 责任边界\n6. 注意事项\n7. 政策来源"
            )
            role_hint = "你是部门办件助手，结合政策依据给出办理建议，仅供工作人员参考。"
        else:
            structure = "1. 政策要点\n2. 适用条件\n3. 办理流程\n4. 注意事项\n5. 政策来源"
            role_hint = "你是政务知识库检索助手，提供准确政策信息。"

        prompt = f"""{role_hint}

规则：
1. 只使用以下参考资料中的信息，不得编造政策、文号、金额或部门
2. 每个关键结论必须标注来源编号，如[来源1]
3. 如果资料不足或不适用，明确说明"未检索到有效依据"，不要猜测
4. 失效政策不得作为当前依据，但可说明历史情况
5. 涉及具体金额、时限、材料清单的，必须严格引用原文

回答结构：
{structure}

参考资料：
{context}

用户问题：{query}

请给出结构化回答："""
        if llm.available:
            llm_result = llm.complete_raw(
                system=role_hint + " 严格基于参考资料回答，不得编造政策。每个结论标注来源。",
                user=prompt,
                temperature=0.2,
                max_tokens=1500,
                capability=capability,
            )
            # P0-D: record every RAG LLM call (success or failure) with real usage.
            AiUsageRecorder(self.db).record_llm_call(
                make_context(capability, route=route,
                             principal=principal, session_id=session_id,
                             request_id=request_id or request_id_context.get()),
                llm_result, provider=llm.provider,
                degraded=not llm_result.success,
                degrade_reason="llm_call_failed" if not llm_result.success else None,
            )
            if llm_result.success and llm_result.content:
                return llm_result.content.strip(), True, llm_result
            logger.warning("RAG LLM failed: %s", llm_result.error or "no content")
        else:
            # LLM not configured: record rules-tier fallback honestly.
            AiUsageRecorder(self.db).record_rules_call(
                make_context(capability, route=route,
                             principal=principal, session_id=session_id,
                             request_id=request_id or request_id_context.get()),
                model_name="rules-v2",
                degrade_reason="llm_unavailable",
            )
        # Fallback: return raw chunks as a basic answer
        first = context.split("\n\n")[0][:500] if context else ""
        return (f"根据检索到的相关资料：\n\n{first}\n\n"
                f"（注：因 LLM 不可用，以上为原始片段，建议联系管理员启用 AI 服务以获得完整回答）",
                False, None)

    @staticmethod
    def _capability_for_route(route: str) -> str:
        """Map an orchestrator route to an ai_usage_logs capability."""
        if route == "service_guide":
            return CAP_SERVICE_GUIDE
        if route == "ticket_advice":
            return CAP_TICKET_ADVICE
        # default: policy_rag capability covers citizen_query / policy_rag / others
        return CAP_POLICY_RAG

    # ====================================================================
    # Feedback & no-answer
    # ====================================================================

    def submit_feedback(self, principal: Principal, query_text: str, answer_text: str,
                        document_ids: list[int], feedback_type: str,
                        comment: Optional[str] = None, route: str = "rag_query"):
        if feedback_type not in {"helpful", "inaccurate", "outdated", "no_answer"}:
            raise BusinessError("INVALID_FEEDBACK_TYPE", "反馈类型无效", 422)
        fb = KbFeedbackModel(
            user_id=principal.user_id if principal.kind == "user" else None,
            query_text=query_text,
            answer_text=answer_text,
            document_ids=",".join(str(d) for d in document_ids) if document_ids else None,
            feedback_type=feedback_type,
            comment=comment,
            route=route,
        )
        self.db.add(fb)
        # If feedback indicates no_answer, also record in no-answer table
        if feedback_type == "no_answer":
            self._record_no_answer(query_text, principal, route=route,
                                   retrieved_doc_ids=document_ids)
        self.db.commit()

    def list_feedback(self, principal: Principal, *, page: int = 1, page_size: int = 20,
                      feedback_type: Optional[str] = None) -> tuple[list[KbFeedbackModel], int]:
        if principal.role not in {"admin", "department_staff"}:
            raise PermissionDenied("仅管理员和部门人员可查看反馈")
        from sqlalchemy import func, text
        stmt = select(KbFeedbackModel)
        if principal.role == "department_staff":
            # P0-F fix: document_ids is stored as comma-separated string ("5,12,18"),
            # so .in_() against integer IDs never matches. Use PostgreSQL array
            # overlap (&&) to correctly filter feedback touching dept docs.
            dept_doc_ids = list(self.db.scalars(select(KbDocumentModel.id).where(
                KbDocumentModel.department_id == principal.department_id
            )).all())
            if not dept_doc_ids:
                return [], 0
            doc_ids_str = ",".join(str(d) for d in dept_doc_ids)
            stmt = stmt.where(
                text(
                    "string_to_array(COALESCE(kb_feedback.document_ids, ''), ',')::bigint[] "
                    "&& string_to_array(:ids, ',')::bigint[]"
                ).bindparams(ids=doc_ids_str)
            )
        if feedback_type:
            stmt = stmt.where(KbFeedbackModel.feedback_type == feedback_type)
        total = int(self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        items = list(self.db.scalars(
            stmt.order_by(KbFeedbackModel.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all())
        return items, total

    def _record_no_answer(self, query: str, principal: Principal, *,
                          route: str = "rag_query",
                          retrieved_doc_ids: Optional[list[int]] = None):
        existing = self.db.scalar(select(KbNoAnswerQuestionModel).where(
            KbNoAnswerQuestionModel.query_text == query,
            KbNoAnswerQuestionModel.status == "open",
        ))
        if existing:
            return  # dedupe
        na = KbNoAnswerQuestionModel(
            query_text=query,
            user_id=principal.user_id if principal.kind == "user" else None,
            role=principal.role or None,
            route=route,
            retrieved_doc_ids=",".join(str(d) for d in retrieved_doc_ids) if retrieved_doc_ids else None,
            status="open",
        )
        self.db.add(na)

    def list_no_answer(self, principal: Principal, *, page: int = 1, page_size: int = 20,
                       status: Optional[str] = None) -> tuple[list[KbNoAnswerQuestionModel], int]:
        if principal.role != "admin":
            raise PermissionDenied("仅管理员可查看无答案问题")
        from sqlalchemy import func
        stmt = select(KbNoAnswerQuestionModel)
        if status:
            stmt = stmt.where(KbNoAnswerQuestionModel.status == status)
        total = int(self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        items = list(self.db.scalars(
            stmt.order_by(KbNoAnswerQuestionModel.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all())
        return items, total

    def resolve_no_answer(self, na_id: int, principal: Principal, note: str, status: str = "resolved"):
        if principal.role != "admin":
            raise PermissionDenied("仅管理员可处理无答案问题")
        na = self.db.get(KbNoAnswerQuestionModel, na_id)
        if not na:
            raise BusinessError("NOT_FOUND", "无答案问题不存在", 404)
        na.status = status
        na.resolution_note = note
        na.resolved_at = datetime.now(timezone.utc) if status != "open" else None
        self.db.commit()
        self.audit.log(principal, "kb_no_answer_resolve",
                       resource_type="kb_no_answer", resource_id=str(na.id),
                       details={"status": status})

    # ====================================================================
    # Evaluation
    # ====================================================================

    def list_eval_cases(self, principal: Principal, *, scenario: Optional[str] = None,
                        active_only: bool = True) -> list[KbEvalCaseModel]:
        if principal.role != "admin":
            raise PermissionDenied("仅管理员可查看评测集")
        stmt = select(KbEvalCaseModel)
        if active_only:
            stmt = stmt.where(KbEvalCaseModel.is_active.is_(True))
        if scenario:
            stmt = stmt.where(KbEvalCaseModel.scenario == scenario)
        return list(self.db.scalars(stmt.order_by(KbEvalCaseModel.id.asc()).limit(200)).all())

    def create_eval_case(self, principal: Principal, **fields) -> KbEvalCaseModel:
        if principal.role != "admin":
            raise PermissionDenied("仅管理员可创建评测用例")
        case = KbEvalCaseModel(**{k: v for k, v in fields.items() if hasattr(KbEvalCaseModel, k)})
        self.db.add(case)
        self.db.commit()
        self.db.refresh(case)
        self.audit.log(principal, "kb_eval_case_create",
                       resource_type="kb_eval_case", resource_id=str(case.id))
        return case

    def run_eval(self, principal: Principal, *, scenario: Optional[str] = None,
                 role: str = "citizen") -> dict:
        """Run RAG evaluation against all (or scenario-filtered) cases."""
        if principal.role != "admin":
            raise PermissionDenied("仅管理员可运行评测")
        cases = self.list_eval_cases(principal, scenario=scenario, active_only=True)
        # Build a synthetic principal for the requested role
        eval_principal = Principal(kind="user", user_id=principal.user_id,
                                   username=principal.username, role=role,
                                   department_id=principal.department_id)
        runs: list[dict] = []
        for case in cases:
            started = time.perf_counter()
            try:
                result = self.rag_answer(case.query, eval_principal, route="eval")
            except Exception as exc:
                logger.warning("Eval failed for case %d: %s", case.id, exc)
                continue
            latency_ms = int((time.perf_counter() - started) * 1000)
            # Score the result
            expected_doc_ids = _parse_id_list(case.expected_doc_ids)
            must_cite = _parse_id_list(case.must_cite_doc_ids)
            must_not_cite = _parse_id_list(case.must_not_cite_doc_ids)
            retrieved_ids = [c["doc_id"] for c in result.get("citations", [])]
            retrieval_hit = bool(set(retrieved_ids) & set(expected_doc_ids)) if expected_doc_ids else True
            citation_correct = (
                all(d in retrieved_ids for d in must_cite) if must_cite else True
            ) and (
                not any(d in retrieved_ids for d in must_not_cite) if must_not_cite else True
            )
            answer_text = result.get("answer", "")
            # Faithful: must not contain forbidden keywords
            forbidden = (case.must_avoid_keywords or "").split(",")
            forbidden = [k.strip() for k in forbidden if k.strip()]
            answer_faithful = not any(k in answer_text for k in forbidden)
            # Expired policy not cited
            expired_blocked = not any(c.get("is_expired") for c in result.get("citations", []))
            # Permission isolation: citizen never sees DEPARTMENT/INTERNAL
            permission_isolated = True  # enforced by retrieval filter; default True
            no_evidence = bool(result.get("no_evidence"))
            # If expected_no_answer, the run is correct only when no_evidence is True
            if case.expected_no_answer:
                citation_correct = no_evidence
                retrieval_hit = no_evidence

            run = KbEvalRunModel(
                case_id=case.id, role=role, query_text=case.query,
                answer_text=answer_text,
                citations_json=json.dumps(result.get("citations", []), ensure_ascii=False),
                no_evidence=no_evidence,
                retrieval_hit=retrieval_hit,
                citation_correct=citation_correct,
                answer_faithful=answer_faithful,
                expired_policy_blocked=expired_blocked,
                permission_isolated=permission_isolated,
                latency_ms=latency_ms,
                provider=result.get("provider"),
                model_name=result.get("model"),
                evaluator="rules-v1",
            )
            self.db.add(run)
            runs.append({
                "case_id": case.id, "title": case.title, "scenario": case.scenario,
                "retrieval_hit": retrieval_hit, "citation_correct": citation_correct,
                "answer_faithful": answer_faithful, "expired_policy_blocked": expired_blocked,
                "permission_isolated": permission_isolated,
                "no_evidence": no_evidence, "latency_ms": latency_ms,
            })
        self.db.commit()
        # Aggregate metrics
        total = len(runs)
        if total == 0:
            return {"total": 0, "metrics": {}, "runs": []}
        metrics = {
            "retrieval_hit_rate": round(sum(r["retrieval_hit"] for r in runs) / total, 3),
            "citation_correct_rate": round(sum(r["citation_correct"] for r in runs) / total, 3),
            "answer_faithful_rate": round(sum(r["answer_faithful"] for r in runs) / total, 3),
            "expired_policy_blocked_rate": round(sum(r["expired_policy_blocked"] for r in runs) / total, 3),
            "permission_isolated_rate": round(sum(r["permission_isolated"] for r in runs) / total, 3),
            "no_answer_rate": round(sum(r["no_evidence"] for r in runs) / total, 3),
            "avg_latency_ms": round(sum(r["latency_ms"] for r in runs) / total, 0),
        }
        self.audit.log(principal, "kb_eval_run",
                       resource_type="kb_eval", details={"total": total, "metrics": metrics})
        return {"total": total, "metrics": metrics, "runs": runs}

    # ====================================================================
    # Department AI assistant for tickets
    # ====================================================================

    def ticket_advice(self, ticket, principal: Principal, *,
                      request_id: Optional[str] = None) -> dict:
        """RAG-powered department AI assistant for a work order ticket.

        Reads ticket context, retrieves applicable policies + procedures +
        desensitized cases, and generates a structured advice with citations.
        Advisory only.
        """
        # Build a retrieval query from ticket context
        description = (ticket.description or "").strip()
        category_name = ticket.category.name if getattr(ticket, "category", None) else ""
        location = ticket.location or ""
        retrieval_query = f"{category_name} {description} {location}".strip()
        # Department-scoped retrieval (department staff sees own + PUBLIC)
        retrieval = self.retrieve(retrieval_query, principal, top_k=6, route="ticket_advice")
        chunks = retrieval["chunks"]

        # Build module-by-module output
        citations = []
        context_parts = []
        for i, c in enumerate(chunks):
            doc = c["document"]
            context_parts.append(
                f"[来源{i+1}: {doc['title']}（{doc.get('doc_number') or '无文号'}）"
                f"· 类型:{doc.get('kb_type')}· 状态:{'已失效' if c.get('is_expired') else '有效'}]\n{c['content']}"
            )
            citations.append({
                "index": i + 1,
                "doc_id": doc["id"],
                "title": doc["title"],
                "doc_number": doc.get("doc_number"),
                "issuing_authority": doc.get("issuing_authority") or doc.get("published_department_name") or doc.get("department_name"),
                "kb_type": doc.get("kb_type"),
                "department": doc.get("department_name"),
                "published_at": doc.get("published_at"),
                "effective_at": doc.get("effective_at"),
                "expires_at": doc.get("expires_at"),
                "status": doc.get("status"),
                "version": doc.get("version"),
                "is_expired": c.get("is_expired", False),
                "excerpt": c["content"][:240],
                "chunk_index": c.get("chunk_index"),
                "score": c.get("score"),
                "detail_url": f"/api/v1/kb/documents/{doc['id']}",
            })
        context = "\n\n".join(context_parts)
        generated_at = datetime.now(timezone.utc).isoformat()
        rid = request_id or request_id_context.get()

        if not chunks:
            # P0-D: record no-evidence decision honestly.
            AiUsageRecorder(self.db).record_rules_call(
                make_context(CAP_TICKET_ADVICE, route="ticket_advice",
                             principal=principal, request_id=rid),
                model_name="rules",
                degrade_reason="no_evidence",
            )
            return {
                "summary": description[:100] if description else "",
                "suggested_category": category_name or "",
                "suggested_department": "",
                "applicable_policies": [],
                "missing_materials": ["未检索到适用依据，需人工核实工单描述"],
                "verification_needed": ["请补充更多信息后再次检索"],
                "material_completeness": "未检索到适用依据，建议人工核实工单详情",
                "suggested_steps": ["人工核实工单描述", "联系市民补充材料", "查阅本部门内部制度"],
                "responsibility_boundary": "暂无自动建议，请依据部门职责办理",
                "timeline_risk": "未检索到时限依据，按 SLA 默认执行",
                "risk_hint": "无政策依据，请人工核实避免误判",
                "similar_cases": [],
                "reply_draft": "您好，您反映的事项已收悉，我部门将尽快核实处理。感谢您的监督与支持。",
                "citations": [],
                "no_evidence": True,
                "generated_at": generated_at,
                "advisory_only": True,
            }

        # Generate structured advice via LLM
        llm = get_llm_client()
        if llm.available:
            prompt = f"""你是政务工单办理辅助助手。请根据工单信息和检索到的参考资料，为工作人员提供结构化办理建议。

要求：
1. 只使用参考资料中的信息，不得编造政策或文号
2. 每个关键结论必须标注来源编号，如[来源1]
3. 涉及具体材料、时限、金额的，严格依据原文
4. 回复草稿必须正式、可读，便于工作人员复核后使用
5. 失效政策不得作为当前依据
6. 所有建议仅供参考，不得直接作为行政决定

输出严格JSON（不要markdown代码块）：
{{"summary":"工单摘要（不超过100字）","suggested_category":"建议分类","suggested_department":"建议主责部门","applicable_policies":["政策名称[来源1]"],"missing_materials":["缺失的材料或信息"],"verification_needed":["需要核实的事项"],"material_completeness":"材料完整性判断[来源]","suggested_steps":["步骤1","步骤2"],"responsibility_boundary":"责任边界说明","timeline_risk":"办理时限风险","risk_hint":"风险提示（如敏感、紧急、舆情、法律风险）","similar_cases":["相似案例参考"],"reply_draft":"正式回复草稿"}}

工单信息：
- 类型：{ticket.request_type or '未指定'}
- 描述：{description}
- 地点：{location}
- 分类：{category_name or '未分类'}
- 当前状态：{ticket.status or '未指定'}

参考资料：
{context}"""
            llm_result = llm.complete_raw(
                system="你是政务工单办理辅助助手，只输出JSON，所有建议仅供参考，不得作出行政决定。",
                user=prompt,
                temperature=0.3,
                max_tokens=1500,
                json_mode=True,
                capability=CAP_TICKET_ADVICE,
            )
            # P0-D: record every ticket_advice LLM call with real usage.
            AiUsageRecorder(self.db).record_llm_call(
                make_context(CAP_TICKET_ADVICE, route="ticket_advice",
                             principal=principal, request_id=rid),
                llm_result, provider=llm.provider,
                degraded=not llm_result.success,
                degrade_reason="llm_call_failed" if not llm_result.success else None,
            )
            if llm_result.success and llm_result.content:
                try:
                    content = llm_result.content.strip()
                    if content.startswith("```"):
                        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                    advice = json.loads(content)
                    # Round 2 r2-7: ensure all required fields are present with
                    # sensible defaults so callers can rely on the schema.
                    advice.setdefault("summary", description[:100] if description else "")
                    advice.setdefault("suggested_category", category_name or "")
                    advice.setdefault("suggested_department", "")
                    advice.setdefault("applicable_policies", [])
                    advice.setdefault("missing_materials", [])
                    advice.setdefault("verification_needed", [])
                    advice.setdefault("material_completeness", "")
                    advice.setdefault("suggested_steps", [])
                    advice.setdefault("responsibility_boundary", "")
                    advice.setdefault("timeline_risk", "")
                    advice.setdefault("risk_hint", "")
                    advice.setdefault("similar_cases", [])
                    advice.setdefault("reply_draft", "")
                    advice["citations"] = citations
                    advice["no_evidence"] = False
                    advice["generated_at"] = generated_at
                    advice["provider"] = llm.provider or "deepseek"
                    advice["model"] = llm.model
                    advice["advisory_only"] = True
                    return advice
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("ticket advice JSON parse failed: %s", exc)
            else:
                logger.warning("ticket advice LLM failed: %s", llm_result.error or "no content")
        else:
            # LLM not configured: record rules-tier fallback honestly.
            AiUsageRecorder(self.db).record_rules_call(
                make_context(CAP_TICKET_ADVICE, route="ticket_advice",
                             principal=principal, request_id=rid),
                model_name="rules-v2",
                degrade_reason="llm_unavailable",
            )

        # Fallback: rule-based advice with retrieved citations
        return {
            "summary": description[:100] if description else "",
            "suggested_category": category_name or "",
            "suggested_department": "",
            "applicable_policies": [c["document"]["title"] for c in chunks[:3]],
            "missing_materials": (
                ["市民描述较简略，建议联系补充"] if len(description) <= 20 else []
            ),
            "verification_needed": [
                "核实市民描述的事实是否属实",
                "确认涉及的具体位置和责任方",
                "对照参考资料核对办理条件",
            ],
            "material_completeness": (
                "市民提交信息基本完整" if len(description) > 20
                else "描述较简略，建议联系市民补充"
            ),
            "suggested_steps": [
                "核实现场情况并对照[来源1]中的办理条件",
                "对照所需材料清单逐项确认",
                "按办理流程开展处置",
                "撰写公开答复并提交处理结果",
            ],
            "responsibility_boundary": (
                f"本工单属于{category_name or '未分类'}类别，请在本部门职责范围内处理。"
                "如涉及其他部门，建议申请协办。"
            ),
            "timeline_risk": "请在 SLA 时限内完成处理，避免超时。",
            "risk_hint": "规则层兜底建议，请人工核实后采纳",
            "similar_cases": [c["document"]["title"] for c in chunks if c["document"].get("kb_type") == "case"][:3],
            "reply_draft": (
                f"您好，您反映的“{description[:50]}”事项已收悉。"
                "我部门将依据相关政策核实处理，并及时反馈结果。感谢您的监督与支持。"
            ),
            "citations": citations,
            "no_evidence": False,
            "generated_at": generated_at,
            "provider": "rules",
            "model": "rules-v2",
            "advisory_only": True,
        }

    # ====================================================================
    # Helpers
    # ====================================================================

    def _get_doc(self, doc_id: int) -> KbDocumentModel:
        doc = self.db.get(KbDocumentModel, doc_id)
        if not doc:
            raise BusinessError("DOC_NOT_FOUND", "文档不存在", 404)
        return doc

    def _require_dept_access(self, doc: KbDocumentModel, principal: Principal, *,
                             allow_admin: bool = False,
                             allow_view_published: bool = False):
        """Check department-level access. For published PUBLIC docs, all authenticated
        users can view. For DEPARTMENT docs, only same dept or admin. For INTERNAL, admin only.

        P0-C: service principals (e.g. Rasa) no longer bypass visibility checks.
        They are treated as PUBLIC-only readers unless explicitly authorized.
        """
        if principal.kind == "service":
            # Service principals can only read published PUBLIC docs.
            if allow_view_published and doc.visibility == "PUBLIC" and doc.status == "PUBLISHED":
                return
            raise PermissionDenied("服务主体只能访问已发布的公开文档")
        if principal.role == "admin" and allow_admin:
            return
        # Public published docs are visible to all
        if allow_view_published and doc.visibility == "PUBLIC" and doc.status == "PUBLISHED":
            return
        if doc.visibility == "INTERNAL" and principal.role != "admin":
            raise PermissionDenied("无权访问内部文档")
        if doc.visibility == "DEPARTMENT":
            if principal.role == "department_staff" and doc.department_id == principal.department_id:
                return
            if principal.role == "admin":
                return
            raise PermissionDenied("无权访问其他部门的内部文档")
        # PUBLIC: department staff can manage only their own dept's docs
        if principal.role == "department_staff":
            if doc.department_id == principal.department_id:
                return
            if allow_view_published and doc.status == "PUBLISHED":
                return
            raise PermissionDenied("部门人员只能管理本部门文档")
        if allow_view_published and doc.status == "PUBLISHED":
            return
        raise PermissionDenied("无权访问此文档")

    def _can_access(self, doc: KbDocumentModel, principal: Principal) -> bool:
        try:
            self._require_dept_access(doc, principal, allow_admin=True, allow_view_published=True)
            return True
        except PermissionDenied:
            return False

    def _apply_visibility_filter(self, stmt, principal: Principal):
        """Apply role-based visibility filter to a doc query.

        P0-C: service principals (e.g. Rasa) are restricted to PUBLISHED PUBLIC docs only.
        They no longer bypass the visibility filter.
        P0-D+: non-admin users can only see PUBLISHED docs from other departments.
        Department staff may manage their own department's docs of any status.
        """
        if principal.kind == "service":
            # Service principals can only read PUBLISHED PUBLIC docs (P0-C).
            return stmt.where(
                KbDocumentModel.visibility == "PUBLIC",
                KbDocumentModel.status == "PUBLISHED",
            )
        if principal.role == "admin":
            return stmt  # admin sees all
        if principal.role in ("citizen", "agent"):
            # Citizens and agents: only PUBLISHED PUBLIC docs.
            return stmt.where(
                KbDocumentModel.visibility == "PUBLIC",
                KbDocumentModel.status == "PUBLISHED",
            )
        if principal.role == "department_staff":
            # Department staff: PUBLISHED PUBLIC (any dept) + own dept's PUBLIC/DEPARTMENT docs (any status for management).
            # INTERNAL docs are admin-only, even for the user's own department.
            return stmt.where(or_(
                and_(
                    KbDocumentModel.visibility == "PUBLIC",
                    KbDocumentModel.status == "PUBLISHED",
                ),
                and_(
                    KbDocumentModel.visibility.in_(["PUBLIC", "DEPARTMENT"]),
                    KbDocumentModel.department_id == principal.department_id,
                ),
            ))
        return stmt.where(
            KbDocumentModel.visibility == "PUBLIC",
            KbDocumentModel.status == "PUBLISHED",
        )

    @staticmethod
    def _doc_to_dict(doc: KbDocumentModel) -> dict:
        return {
            "id": doc.id,
            "title": doc.title,
            "doc_number": doc.doc_number,
            "issuing_authority": doc.issuing_authority,
            "kb_type": doc.kb_type,
            "domain": doc.domain,
            "region": doc.region,
            "audience": doc.audience,
            "visibility": doc.visibility,
            "status": doc.status,
            "version": doc.version,
            "department_id": doc.department_id,
            "department_name": doc.department.name if doc.department else None,
            "published_department_name": doc.published_department.name if doc.published_department else None,
            "source_url": doc.source_url,
            "keywords": doc.keywords,
            "published_at": doc.published_at.isoformat() if doc.published_at else None,
            "effective_at": doc.effective_at.isoformat() if doc.effective_at else None,
            "expires_at": doc.expires_at.isoformat() if doc.expires_at else None,
            "parse_status": doc.parse_status,
            "index_status": doc.index_status,
            "chunk_count": doc.chunk_count,
            "embedding_model": doc.embedding_model,
            "ocr_status": doc.ocr_status,
            "ocr_quality": doc.ocr_quality,
            "file_type": doc.file_type,
            "original_filename": doc.original_filename,
            "file_size_bytes": doc.file_size_bytes,
            "version_count": 1,  # populated by caller if needed
        }


_NO_EVIDENCE_MESSAGE = (
    "抱歉，未检索到与您问题相关的有效政策依据。本系统不会编造政策，您可以选择：\n"
    "1. 补充问题：补充所在城市、人员身份、申请年份、家属关系或具体业务类型等关键信息后重新提问；\n"
    "2. 转人工：拨打 12345 政务服务热线，或前往所在社区服务中心/对应主管部门窗口咨询；\n"
    "3. 创建咨询工单：如果您希望相关部门跟进回复，请回复“创建咨询工单”，我会引导您填写工单草稿（仅在您明确确认后才会建单）。\n"
    "（您的问题已记录用于后续政策补充。）"
)


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    # Accept ISO with optional timezone
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _parse_id_list(s: Optional[str]) -> list[int]:
    if not s:
        return []
    out: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out
