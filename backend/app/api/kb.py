"""Knowledge Base API endpoints.

提供文档生命周期、版本管理、审核、重建索引、切片预览、文件下载、
反馈、审计、评测、部门 AI 办件助手以及 RAG 查询等接口。

权限模型：
- 市民 citizen：仅可查询已发布的 PUBLIC 文档与发起 RAG 咨询/反馈
- 坐席 agent：可查询 PUBLIC 文档与发起 RAG 咨询/反馈
- 部门人员 department_staff：可上传/管理本部门文档、提交审核、查询反馈、调用 AI 办件助手
- 管理员 admin：全部能力 + 直发/审核/下线/失效/重建索引/无答案处理/评测管理
"""
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..authorization import Principal
from ..database import get_db
from ..schemas import SuccessResponse
from ..services.kb_service import KnowledgeBaseService
from .dependencies import get_current_principal, get_user_principal

router = APIRouter(prefix="/api/v1/kb", tags=["knowledge-base"])


def get_service(db: Session = Depends(get_db)) -> KnowledgeBaseService:
    return KnowledgeBaseService(db)


# ============================================================================
# Schemas
# ============================================================================

class DocCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    doc_number: Optional[str] = Field(default=None, max_length=200)
    issuing_authority: Optional[str] = Field(default=None, max_length=200)
    kb_type: str = Field(default="policy", pattern="^(policy|guide|faq|internal|procedure|case)$")
    domain: Optional[str] = Field(default=None, max_length=200)
    region: Optional[str] = Field(default=None, max_length=200)
    audience: Optional[str] = Field(default=None, max_length=200)
    file_type: str = Field(default="text")
    visibility: str = Field(default="PUBLIC", pattern="^(PUBLIC|DEPARTMENT|INTERNAL)$")
    keywords: Optional[str] = None
    source_url: Optional[str] = Field(default=None, max_length=1000)
    effective_at: Optional[str] = None
    expires_at: Optional[str] = None
    raw_content: Optional[str] = None
    department_id: Optional[int] = None
    tags: Optional[list[str]] = None
    auto_publish: bool = False


class DocUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=500)
    doc_number: Optional[str] = Field(default=None, max_length=200)
    issuing_authority: Optional[str] = Field(default=None, max_length=200)
    kb_type: Optional[str] = Field(default=None, pattern="^(policy|guide|faq|internal|procedure|case)$")
    domain: Optional[str] = Field(default=None, max_length=200)
    region: Optional[str] = Field(default=None, max_length=200)
    audience: Optional[str] = Field(default=None, max_length=200)
    visibility: Optional[str] = Field(default=None, pattern="^(PUBLIC|DEPARTMENT|INTERNAL)$")
    keywords: Optional[str] = None
    source_url: Optional[str] = Field(default=None, max_length=1000)
    effective_at: Optional[str] = None
    expires_at: Optional[str] = None
    department_id: Optional[int] = None
    tags: Optional[list[str]] = None


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(publish|reject)$")
    comment: str = Field(default="", max_length=2000)


class DirectPublishRequest(BaseModel):
    comment: str = Field(default="", max_length=2000)


class WithdrawRequest(BaseModel):
    reason: str = Field(default="", max_length=2000)


class ExpireRequest(BaseModel):
    reason: str = Field(default="", max_length=2000)


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    region: Optional[str] = Field(default=None, max_length=200)
    domain: Optional[str] = Field(default=None, max_length=200)
    audience: Optional[str] = Field(default=None, max_length=200)
    top_k: Optional[int] = Field(default=None, ge=1, le=20)


class FeedbackRequest(BaseModel):
    query_text: str = Field(min_length=1, max_length=2000)
    answer_text: Optional[str] = None
    document_ids: list[int] = []
    feedback_type: str = Field(pattern="^(helpful|inaccurate|outdated|no_answer)$")
    comment: Optional[str] = None
    route: Optional[str] = Field(default=None, max_length=64)


class NoAnswerResolveRequest(BaseModel):
    status: str = Field(pattern="^(resolved|wont_fix|assigned)$")
    note: str = Field(default="", max_length=2000)


class EvalCaseCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=500)
    domain: Optional[str] = Field(default=None, max_length=200)
    scenario: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=2, max_length=4000)
    expected_answer_summary: Optional[str] = None
    expected_doc_ids: Optional[str] = Field(default=None, max_length=500)
    must_cite_doc_ids: Optional[str] = Field(default=None, max_length=500)
    must_not_cite_doc_ids: Optional[str] = Field(default=None, max_length=500)
    must_avoid_keywords: Optional[str] = None
    expected_role: str = Field(default="citizen", pattern="^(citizen|agent|department_staff|admin)$")
    expected_no_answer: bool = False
    notes: Optional[str] = None
    is_active: bool = True


class EvalRunRequest(BaseModel):
    scenario: Optional[str] = Field(default=None, max_length=64)
    role: str = Field(default="citizen", pattern="^(citizen|agent|department_staff|admin)$")


# ============================================================================
# Helpers
# ============================================================================

def _doc_summary(doc) -> dict:
    """Serialize a KbDocumentModel to a summary dict for list responses."""
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
        "parent_version_id": doc.parent_version_id,
        "replaces_doc_id": doc.replaces_doc_id,
        "department_id": doc.department_id,
        "department_name": doc.department.name if doc.department else None,
        "published_department_name": doc.published_department.name if doc.published_department else None,
        "source_url": doc.source_url,
        "keywords": doc.keywords,
        "chunk_count": doc.chunk_count,
        "parse_status": doc.parse_status,
        "index_status": doc.index_status,
        "ocr_status": doc.ocr_status,
        "file_type": doc.file_type,
        "original_filename": doc.original_filename,
        "file_size_bytes": doc.file_size_bytes,
        "embedding_model": doc.embedding_model,
        "review_comment": doc.review_comment,
        "rejected_reason": doc.rejected_reason,
        "published_at": doc.published_at.isoformat() if doc.published_at else None,
        "effective_at": doc.effective_at.isoformat() if doc.effective_at else None,
        "expires_at": doc.expires_at.isoformat() if doc.expires_at else None,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def _doc_detail(doc) -> dict:
    """Full document detail including tags and metadata."""
    import json as _json
    summary = _doc_summary(doc)
    tags = []
    if doc.tags:
        try:
            tags = _json.loads(doc.tags) if doc.tags.startswith("[") else [t.strip() for t in doc.tags.split(",") if t.strip()]
        except Exception:
            tags = []
    meta = {}
    if doc.meta_json:
        try:
            meta = _json.loads(doc.meta_json)
        except Exception:
            meta = {}
    summary.update({
        "tags": tags,
        "meta": meta,
        "uploaded_by_user_id": doc.uploaded_by_user_id,
        "reviewed_by_user_id": doc.reviewed_by_user_id,
        "published_by_user_id": doc.published_by_user_id,
        "storage_key": doc.storage_key,
        "mime_type": doc.mime_type,
        "ocr_quality": doc.ocr_quality,
        "chunking_version": doc.chunking_version,
        "has_file": bool(doc.storage_key),
        "has_content": bool(doc.raw_content and doc.raw_content.strip()),
    })
    return summary


def _chunk_to_dict(chunk) -> dict:
    import json as _json
    keywords = []
    if chunk.keywords:
        try:
            keywords = _json.loads(chunk.keywords)
        except Exception:
            keywords = []
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "char_count": chunk.char_count,
        "token_count": chunk.token_count,
        "chunk_hash": chunk.chunk_hash,
        "keywords": keywords,
        "has_embedding": True,  # ORM cannot reliably read pgvector column; assume set
        "embedding_model": chunk.embedding_model,
        "embedding_provider": chunk.embedding_provider,
        "embedding_dimension": chunk.embedding_dimension,
        "embedding_fallback": chunk.embedding_fallback,
        "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
    }


def _feedback_to_dict(fb) -> dict:
    return {
        "id": fb.id,
        "user_id": fb.user_id,
        "query_text": fb.query_text,
        "answer_text": fb.answer_text,
        "document_ids": fb.document_ids.split(",") if fb.document_ids else [],
        "feedback_type": fb.feedback_type,
        "comment": fb.comment,
        "route": fb.route,
        "created_at": fb.created_at.isoformat() if fb.created_at else None,
    }


def _no_answer_to_dict(na) -> dict:
    return {
        "id": na.id,
        "query_text": na.query_text,
        "user_id": na.user_id,
        "role": na.role,
        "route": na.route,
        "retrieved_doc_ids": na.retrieved_doc_ids.split(",") if na.retrieved_doc_ids else [],
        "status": na.status,
        "assigned_department_id": na.assigned_department_id,
        "resolution_note": na.resolution_note,
        "created_at": na.created_at.isoformat() if na.created_at else None,
        "resolved_at": na.resolved_at.isoformat() if na.resolved_at else None,
    }


def _eval_case_to_dict(case) -> dict:
    return {
        "id": case.id,
        "title": case.title,
        "domain": case.domain,
        "scenario": case.scenario,
        "query": case.query,
        "expected_answer_summary": case.expected_answer_summary,
        "expected_doc_ids": case.expected_doc_ids,
        "must_cite_doc_ids": case.must_cite_doc_ids,
        "must_not_cite_doc_ids": case.must_not_cite_doc_ids,
        "must_avoid_keywords": case.must_avoid_keywords,
        "expected_role": case.expected_role,
        "expected_no_answer": case.expected_no_answer,
        "notes": case.notes,
        "is_active": case.is_active,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
    }


# ============================================================================
# Document CRUD
# ============================================================================

@router.post("/documents", response_model=SuccessResponse[dict])
def create_document(
    payload: DocCreateRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Create a new KB document from raw text content (DRAFT by default)."""
    doc = service.create_document(principal, **payload.model_dump(exclude_none=True))
    return SuccessResponse(data={
        "id": doc.id, "title": doc.title, "status": doc.status,
        "version": doc.version, "chunk_count": doc.chunk_count,
    })


@router.post("/documents/upload", response_model=SuccessResponse[dict])
def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    doc_number: Optional[str] = Form(None),
    issuing_authority: Optional[str] = Form(None),
    kb_type: str = Form("policy"),
    domain: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    audience: Optional[str] = Form(None),
    visibility: str = Form("PUBLIC"),
    keywords: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    effective_at: Optional[str] = Form(None),
    expires_at: Optional[str] = Form(None),
    department_id: Optional[int] = Form(None),
    tags: Optional[str] = Form(None),
    doc_id: Optional[int] = Form(None),
    auto_publish: bool = Form(False),
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Upload a file (PDF/Word/Markdown/Text) and create a new document or new version.

    - 若提供 doc_id，则为该文档创建新版本（旧版本保留）。
    - 文件类型必须为 pdf/docx/md/markdown/txt。
    - 解析失败的扫描件将标记 ocr_status='required'，但仍可保存以供后续 OCR。
    """
    file_bytes = file.file.read()
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    doc = service.upload_file(
        principal,
        doc_id=doc_id,
        file_bytes=file_bytes,
        filename=file.filename or "upload.bin",
        mime_type=file.content_type,
        title=title,
        doc_number=doc_number,
        kb_type=kb_type,
        domain=domain,
        region=region,
        audience=audience,
        visibility=visibility,
        keywords=keywords,
        source_url=source_url,
        effective_at=effective_at,
        expires_at=expires_at,
        department_id=department_id,
        tags=tags_list,
        auto_publish=auto_publish,
        issuing_authority=issuing_authority,
    )
    return SuccessResponse(data=_doc_summary(doc))


@router.get("/documents", response_model=SuccessResponse[dict])
def list_documents(
    status: Optional[str] = Query(None),
    kb_type: Optional[str] = Query(None),
    visibility: Optional[str] = Query(None),
    department_id: Optional[int] = Query(None, gt=0),
    domain: Optional[str] = Query(None, max_length=200),
    keyword: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """List documents with role-based permission filter and pagination."""
    items, total = service.list_documents(
        principal,
        status=status, kb_type=kb_type, visibility=visibility,
        department_id=department_id, domain=domain, keyword=keyword,
        limit=page_size, offset=(page - 1) * page_size,
    )
    return SuccessResponse(data={
        "items": [_doc_summary(d) for d in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/documents/{doc_id}", response_model=SuccessResponse[dict])
def get_document(
    doc_id: int,
    principal: Principal = Depends(get_current_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Get full document detail including metadata and file info."""
    doc = service.get_document(doc_id, principal)
    return SuccessResponse(data=_doc_detail(doc))


@router.patch("/documents/{doc_id}", response_model=SuccessResponse[dict])
def update_document(
    doc_id: int,
    payload: DocUpdateRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Update document metadata. Only DRAFT/REJECTED documents can be edited."""
    fields = payload.model_dump(exclude_none=True)
    doc = service.update_metadata(doc_id, principal, **fields)
    return SuccessResponse(data=_doc_summary(doc))


# ============================================================================
# Document lifecycle: submit review, review, direct publish, withdraw, expire
# ============================================================================

@router.post("/documents/{doc_id}/submit-review", response_model=SuccessResponse[dict])
def submit_review(
    doc_id: int,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Submit a DRAFT/REJECTED document for admin review."""
    service.submit_for_review(doc_id, principal)
    return SuccessResponse(data={"id": doc_id, "status": "REVIEWING"})


@router.post("/documents/{doc_id}/review", response_model=SuccessResponse[dict])
def review_document(
    doc_id: int,
    payload: ReviewRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Admin approves or rejects a document under review."""
    service.review_document(doc_id, payload.decision, payload.comment, principal)
    new_status = "PUBLISHED" if payload.decision == "publish" else "REJECTED"
    return SuccessResponse(data={"id": doc_id, "status": new_status})


@router.post("/documents/{doc_id}/publish", response_model=SuccessResponse[dict])
def direct_publish(
    doc_id: int,
    payload: DirectPublishRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Admin directly publishes a DRAFT document (skips review)."""
    service.direct_publish(doc_id, principal, payload.comment)
    return SuccessResponse(data={"id": doc_id, "status": "PUBLISHED"})


@router.post("/documents/{doc_id}/withdraw", response_model=SuccessResponse[dict])
def withdraw_document(
    doc_id: int,
    payload: WithdrawRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Withdraw a published document (mark as WITHDRAWN)."""
    service.withdraw_document(doc_id, principal, payload.reason)
    return SuccessResponse(data={"id": doc_id, "status": "WITHDRAWN"})


@router.post("/documents/{doc_id}/expire", response_model=SuccessResponse[dict])
def expire_document(
    doc_id: int,
    payload: ExpireRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Mark a published document as expired (e.g., policy superseded)."""
    service.expire_document(doc_id, principal, payload.reason)
    return SuccessResponse(data={"id": doc_id, "status": "EXPIRED"})


# ============================================================================
# Indexing & chunks preview
# ============================================================================

@router.post("/documents/{doc_id}/reindex", response_model=SuccessResponse[dict])
def reindex_document(
    doc_id: int,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Re-parse and re-build vector index for a document."""
    service.reindex(doc_id, principal)
    doc = service.get_document(doc_id, principal)
    return SuccessResponse(data={
        "id": doc.id,
        "parse_status": doc.parse_status,
        "index_status": doc.index_status,
        "chunk_count": doc.chunk_count,
        "embedding_model": doc.embedding_model,
    })


@router.get("/documents/{doc_id}/versions", response_model=SuccessResponse[list[dict]])
def list_versions(
    doc_id: int,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """List all versions of a document along its version chain."""
    versions = service.list_versions(doc_id, principal)
    return SuccessResponse(data=[_doc_summary(v) for v in versions])


@router.get("/documents/{doc_id}/chunks", response_model=SuccessResponse[dict])
def list_chunks(
    doc_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Preview chunks of a document (for verification/debug)."""
    items, total = service.list_chunks(doc_id, principal, limit=page_size, offset=(page - 1) * page_size)
    return SuccessResponse(data={
        "items": [_chunk_to_dict(c) for c in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


# ============================================================================
# File download
# ============================================================================

@router.get("/documents/{doc_id}/download")
def download_document(
    doc_id: int,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Download the original uploaded file of a document from object storage."""
    data, filename, content_type = service.download_file(doc_id, principal)
    safe_name = filename or "document"
    disposition = f"attachment; filename=document.bin; filename*=UTF-8''{quote(safe_name, safe='')}"
    import io
    return StreamingResponse(
        io.BytesIO(data),
        media_type=content_type or "application/octet-stream",
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(data)),
            "X-Content-Type-Options": "nosniff",
        },
    )


# ============================================================================
# RAG query & retrieval
# ============================================================================

@router.post("/query", response_model=SuccessResponse[dict])
def rag_query(
    payload: RagQueryRequest,
    principal: Principal = Depends(get_current_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Full RAG pipeline: permission-filtered retrieval + LLM answer with citations."""
    result = service.rag_answer(
        payload.query, principal,
        region=payload.region, domain=payload.domain, audience=payload.audience,
    )
    return SuccessResponse(data=result)


@router.post("/retrieve", response_model=SuccessResponse[dict])
def retrieve_only(
    payload: RagQueryRequest,
    principal: Principal = Depends(get_current_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Retrieve-only endpoint (no LLM generation) for admin/agent debugging."""
    result = service.retrieve(
        payload.query, principal,
        region=payload.region, domain=payload.domain, audience=payload.audience,
        top_k=payload.top_k,
    )
    return SuccessResponse(data=result)


# ============================================================================
# Feedback
# ============================================================================

@router.post("/feedback", response_model=SuccessResponse[dict])
def submit_feedback(
    payload: FeedbackRequest,
    principal: Principal = Depends(get_current_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Submit feedback on a RAG answer (helpful/inaccurate/outdated/no_answer)."""
    service.submit_feedback(
        principal, payload.query_text, payload.answer_text or "",
        payload.document_ids, payload.feedback_type, payload.comment,
        route=payload.route or "rag_query",
    )
    return SuccessResponse(data={"status": "recorded"})


@router.get("/feedback", response_model=SuccessResponse[dict])
def list_feedback(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    feedback_type: Optional[str] = Query(None, pattern="^(helpful|inaccurate|outdated|no_answer)$"),
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """List feedback entries (admin sees all, department_staff sees own dept's)."""
    items, total = service.list_feedback(
        principal, page=page, page_size=page_size, feedback_type=feedback_type,
    )
    return SuccessResponse(data={
        "items": [_feedback_to_dict(f) for f in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


# ============================================================================
# No-answer questions (admin)
# ============================================================================

@router.get("/no-answer", response_model=SuccessResponse[dict])
def list_no_answer(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, pattern="^(open|assigned|resolved|wont_fix)$"),
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """List user queries that produced no evidence (admin only)."""
    items, total = service.list_no_answer(
        principal, page=page, page_size=page_size, status=status,
    )
    return SuccessResponse(data={
        "items": [_no_answer_to_dict(n) for n in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.post("/no-answer/{na_id}/resolve", response_model=SuccessResponse[dict])
def resolve_no_answer(
    na_id: int,
    payload: NoAnswerResolveRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Resolve or reassign a no-answer question (admin only)."""
    service.resolve_no_answer(na_id, principal, payload.note, payload.status)
    return SuccessResponse(data={"id": na_id, "status": payload.status})


# ============================================================================
# Evaluation (admin)
# ============================================================================

@router.get("/eval/cases", response_model=SuccessResponse[list[dict]])
def list_eval_cases(
    scenario: Optional[str] = Query(None, max_length=64),
    active_only: bool = Query(True),
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """List RAG evaluation cases (admin only)."""
    cases = service.list_eval_cases(principal, scenario=scenario, active_only=active_only)
    return SuccessResponse(data=[_eval_case_to_dict(c) for c in cases])


@router.post("/eval/cases", response_model=SuccessResponse[dict])
def create_eval_case(
    payload: EvalCaseCreateRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Create a new evaluation case (admin only)."""
    case = service.create_eval_case(principal, **payload.model_dump(exclude_none=True))
    return SuccessResponse(data=_eval_case_to_dict(case))


@router.post("/eval/run", response_model=SuccessResponse[dict])
def run_eval(
    payload: EvalRunRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Run RAG evaluation across all (or scenario-filtered) cases.

    Returns per-case run results plus aggregate metrics:
    - retrieval_hit_rate: 命中率
    - citation_correct_rate: 引用准确率
    - answer_faithful_rate: 忠实度
    - expired_policy_blocked_rate: 失效政策拦截率
    - permission_isolated_rate: 权限隔离率
    - no_answer_rate: 无答案率
    - avg_latency_ms: 平均延迟
    """
    result = service.run_eval(principal, scenario=payload.scenario, role=payload.role)
    return SuccessResponse(data=result)


# ============================================================================
# Department AI ticket advice (RAG-powered)
# ============================================================================

@router.post("/tickets/{ticket_id}/advice", response_model=SuccessResponse[dict])
def ticket_advice(
    ticket_id: str,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """RAG-powered department AI assistant for a work order ticket.

    Returns modular advice: 适用依据/材料检查/办理流程/时限与风险/相似案例/回复草稿
    All output is advisory only — never auto-sent to citizens.
    """
    from ..authorization import AuthorizationPolicy
    from ..errors import PermissionDenied, TicketNotFound
    from ..repositories.ai import AiRepository
    # Reuse the request-scoped session to fetch the ticket (with category eager-loaded)
    ticket = AiRepository(service.db).ticket(ticket_id)
    if not ticket:
        raise TicketNotFound(ticket_id)
    AuthorizationPolicy.require_view(principal, ticket)
    if principal.role not in {"department_staff", "agent", "admin"}:
        raise PermissionDenied("只有工作人员可以使用 AI 办件助手")
    advice = service.ticket_advice(ticket, principal)
    service.audit.log(
        principal, "kb_ticket_advice",
        resource_type="ticket", resource_id=ticket_id,
        details={"provider": advice.get("provider"), "no_evidence": advice.get("no_evidence")},
    )
    return SuccessResponse(data=advice)


# ============================================================================
# Round 2 r2-7: AI advice review (adopt / adopt-with-edits / reject)
# ============================================================================

class AdviceReviewRequest(BaseModel):
    """Three-state human confirmation for AI ticket advice.

    Round 2 r2-7: AI advice must NEVER auto-dispatch, auto-transfer,
    auto-reject, auto-close or auto-send the final reply. A human operator
    must explicitly adopt, adopt-with-edits, or reject each advice.
    """
    decision: str = Field(..., description="adopted | adopted_with_edits | rejected")
    edit_summary: Optional[str] = Field(default=None, max_length=1000,
                                         description="修改内容摘要（仅 adopted_with_edits 必填）")
    advice_snapshot: Optional[dict] = Field(default=None,
                                             description="采纳时的 advice 快照（可选，用于审计追溯）")


@router.post("/tickets/{ticket_id}/advice/review", response_model=SuccessResponse[dict])
def ticket_advice_review(
    ticket_id: str,
    payload: AdviceReviewRequest,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """Record the human operator's three-state decision on AI ticket advice.

    Decisions are recorded in audit_logs (action=ai_advice_review) — no
    ticket status change is made here. The AI advice remains advisory only.
    """
    from ..authorization import AuthorizationPolicy
    from ..errors import BusinessError, PermissionDenied, TicketNotFound
    from ..repositories.ai import AiRepository
    from datetime import datetime, timezone

    valid_decisions = {"adopted", "adopted_with_edits", "rejected"}
    if payload.decision not in valid_decisions:
        raise BusinessError("INVALID_DECISION",
                            f"decision 必须是 {valid_decisions} 之一", 400)
    if payload.decision == "adopted_with_edits" and not (payload.edit_summary or "").strip():
        raise BusinessError("EDIT_SUMMARY_REQUIRED",
                            "修改后采纳必须填写修改内容摘要", 400)

    ticket = AiRepository(service.db).ticket(ticket_id)
    if not ticket:
        raise TicketNotFound(ticket_id)
    AuthorizationPolicy.require_view(principal, ticket)
    if principal.role not in {"department_staff", "agent", "admin"}:
        raise PermissionDenied("只有工作人员可以审核 AI 办件建议")

    operated_at = datetime.now(timezone.utc).isoformat()
    service.audit.log(
        principal, "ai_advice_review",
        resource_type="ticket", resource_id=ticket_id,
        details={
            "decision": payload.decision,
            "edit_summary": payload.edit_summary,
            "operator_user_id": principal.user_id,
            "operator_role": principal.role,
            "operated_at": operated_at,
            "advisory_only": True,
            # NOTE: no ticket status change — AI advice never auto-dispatches
            # / auto-transfers / auto-rejects / auto-closes / auto-sends.
        },
    )
    return SuccessResponse(data={
        "ticket_id": ticket_id,
        "decision": payload.decision,
        "edit_summary": payload.edit_summary,
        "operator_user_id": principal.user_id,
        "operator_role": principal.role,
        "operated_at": operated_at,
        "advisory_only": True,
        "status_changed": False,  # explicit: this endpoint does NOT touch ticket status
    })


@router.get("/tickets/{ticket_id}/advice/reviews", response_model=SuccessResponse[list[dict]])
def list_ticket_advice_reviews(
    ticket_id: str,
    principal: Principal = Depends(get_user_principal),
    service: KnowledgeBaseService = Depends(get_service),
):
    """List AI advice review history for a ticket (department_staff/agent/admin only).

    Round 3 r3-3: returns the audit trail of three-state human confirmation
    decisions recorded by ``ticket_advice_review``. Each record is advisory
    only and never mutates ticket status/version.
    """
    import json
    from sqlalchemy import select
    from ..authorization import AuthorizationPolicy
    from ..errors import PermissionDenied, TicketNotFound
    from ..models import AuditLogModel, UserModel
    from ..repositories.ai import AiRepository

    ticket = AiRepository(service.db).ticket(ticket_id)
    if not ticket:
        raise TicketNotFound(ticket_id)
    AuthorizationPolicy.require_view(principal, ticket)
    if principal.role not in {"department_staff", "agent", "admin"}:
        raise PermissionDenied("只有工作人员可以查看 AI 办件建议审核记录")

    stmt = (
        select(AuditLogModel, UserModel.display_name)
        .outerjoin(UserModel, UserModel.id == AuditLogModel.actor_user_id)
        .where(
            AuditLogModel.action == "ai_advice_review",
            AuditLogModel.resource_type == "ticket",
            AuditLogModel.resource_id == ticket_id,
        )
        .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
    )
    rows = service.db.execute(stmt).all()
    items: list[dict] = []
    for log, operator_name in rows:
        try:
            details = json.loads(log.details) if log.details else {}
        except (TypeError, ValueError):
            details = {}
        operated_at = details.get("operated_at")
        if not operated_at and log.created_at is not None:
            operated_at = log.created_at.isoformat()
        items.append({
            "id": log.id,
            "ticket_id": ticket_id,
            "decision": details.get("decision"),
            "edit_summary": details.get("edit_summary"),
            "advice_snapshot": details.get("advice_snapshot"),
            "operator_user_id": details.get("operator_user_id") or log.actor_user_id,
            "operator_role": details.get("operator_role"),
            "operator_name": operator_name,
            "operated_at": operated_at,
            "advisory_only": bool(details.get("advisory_only", True)),
        })
    return SuccessResponse(data=items)
