"""Strict response schemas for triage_assistant / handling_assistant LLM outputs.

Validation failures must trigger an explainable rules fallback — never persist
unchecked model JSON into ai_suggestions.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

# Phrases that assert completed handling facts (must not appear without real facts).
FABRICATED_HANDLING_FACTS = (
    "已经解决",
    "已经修复",
    "已完成维修",
    "已现场核查",
    "已派人",
    "已恢复正常",
    "已经办结",
    "已经处理完成",
    "已处理完成",
    "维修完成",
    "已修复",
    "已办结",
    "处理完毕",
    "已处置完毕",
)

# Capability-exclusive top-level keys. Presence of the other capability's keys → reject.
TRIAGE_EXCLUSIVE_KEYS = frozenset({
    "department_candidates",
    "sla_recommendation",
    "intake_notice_draft",
    "classification",
    "urgency",
    "completeness",
})
HANDLING_EXCLUSIVE_KEYS = frozenset({
    "verification_checklist",
    "handling_plan",
    "policy_references",
    "risk_warnings",
    "missing_handling_facts",
    "collaboration_suggestions",
    "evidence_checklist",
    "reply_template",
    "reply_draft",
    "facts_sufficient",
})

URGENCY_LEVELS = frozenset({"normal", "expedited", "urgent", "major"})
RECOMMENDATION_LEVELS = frozenset({"high", "medium", "low"})


class SchemaValidationResult(BaseModel):
    """Outcome of validating an LLM capability payload."""
    ok: bool
    data: Optional[dict[str, Any]] = None
    degrade_reason: Optional[str] = None
    detail: Optional[str] = None


class CaseSummaryTriage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str = Field(min_length=1, max_length=2000)
    location: str = Field(default="", max_length=500)
    duration: str = Field(default="", max_length=200)
    affected_scope: str = Field(default="", max_length=500)


class ClassificationBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    request_type: str = Field(min_length=1, max_length=64)
    category: str = Field(default="", max_length=200)
    subcategory: str = Field(default="", max_length=200)
    reason: str = Field(default="", max_length=1000)


class UrgencyBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    level: Literal["normal", "expedited", "urgent", "major"]
    emergency: bool = False
    reason: str = Field(default="", max_length=1000)

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            aliases = {"high": "urgent", "low": "normal", "medium": "expedited"}
            return aliases.get(normalized, normalized)
        return value


class CompletenessBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    complete: bool
    known_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    completeness_score: Optional[int] = Field(default=None, ge=0, le=100)


class DepartmentCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    department_name: str = Field(min_length=1, max_length=200)
    recommendation_level: Literal["high", "medium", "low"] = "medium"
    reason: str = Field(default="", max_length=1000)
    department_id: Optional[int] = None
    historical_cases: Optional[int] = Field(default=None, ge=0)
    score: Optional[float] = Field(default=None, ge=0, le=1)

    @field_validator("recommendation_level", mode="before")
    @classmethod
    def normalize_level(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class SlaRecommendation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    response_deadline: str = Field(default="", max_length=500)
    handling_deadline: str = Field(default="", max_length=500)
    reason: str = Field(default="", max_length=1000)


class TriageAssistantResponse(BaseModel):
    """Strict schema for triage_assistant LLM / rules payloads."""
    model_config = ConfigDict(extra="ignore")

    case_summary: CaseSummaryTriage
    classification: ClassificationBlock
    urgency: UrgencyBlock
    completeness: CompletenessBlock
    department_candidates: list[DepartmentCandidate] = Field(default_factory=list, max_length=20)
    sla_recommendation: SlaRecommendation = Field(default_factory=SlaRecommendation)
    intake_notice_draft: str = Field(min_length=1, max_length=2000)
    advisory_only: Literal[True] = True
    capability: Optional[str] = None
    confidence_labels: Optional[dict[str, int]] = None
    confidence: Optional[int] = Field(default=None, ge=0, le=100)

    @field_validator("confidence_labels", mode="before")
    @classmethod
    def validate_confidence_labels(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("confidence_labels must be an object")
        out: dict[str, int] = {}
        for key, raw in value.items():
            score = int(raw)
            if score < 0 or score > 100:
                raise ValueError(f"confidence_labels.{key} out of range 0-100")
            out[str(key)] = score
        return out

    @model_validator(mode="before")
    @classmethod
    def reject_handling_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise ValueError("payload must be an object")
        leaked = sorted(HANDLING_EXCLUSIVE_KEYS & set(data.keys()))
        if leaked:
            raise ValueError(f"cross_capability_fields:{','.join(leaked)}")
        return data


class CaseSummaryHandling(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str = Field(min_length=1, max_length=2000)
    assigned_department: str = Field(default="", max_length=200)
    classification: str = Field(default="", max_length=200)
    known_facts: list[str] = Field(default_factory=list)


class HandlingAssistantResponse(BaseModel):
    """Strict schema for handling_assistant LLM / rules payloads."""
    model_config = ConfigDict(extra="ignore")

    case_summary: CaseSummaryHandling
    verification_checklist: list[str] = Field(min_length=1, max_length=50)
    handling_plan: list[str] = Field(min_length=1, max_length=50)
    policy_references: list[str] = Field(default_factory=list, max_length=30)
    risk_warnings: list[str] = Field(default_factory=list, max_length=30)
    missing_handling_facts: list[str] = Field(default_factory=list, max_length=30)
    collaboration_suggestions: list[str] = Field(default_factory=list, max_length=30)
    evidence_checklist: list[str] = Field(default_factory=list, max_length=30)
    reply_template: str = Field(min_length=1, max_length=4000)
    reply_draft: str = Field(min_length=1, max_length=4000)
    facts_sufficient: bool
    advisory_only: Literal[True] = True
    capability: Optional[str] = None
    confidence: Optional[int] = Field(default=None, ge=0, le=100)

    @model_validator(mode="before")
    @classmethod
    def reject_triage_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise ValueError("payload must be an object")
        leaked = sorted(TRIAGE_EXCLUSIVE_KEYS & set(data.keys()))
        if leaked:
            raise ValueError(f"cross_capability_fields:{','.join(leaked)}")
        return data


def _contains_fabricated_facts(blob: str) -> Optional[str]:
    for phrase in FABRICATED_HANDLING_FACTS:
        if phrase in blob:
            return phrase
    return None


def validate_triage_response(payload: Any) -> SchemaValidationResult:
    """Validate triage_assistant payload. On failure → rules degrade."""
    if payload is None:
        return SchemaValidationResult(ok=False, degrade_reason="empty_payload", detail="payload is null")
    if not isinstance(payload, dict):
        return SchemaValidationResult(ok=False, degrade_reason="invalid_payload_type", detail="payload is not an object")
    try:
        model = TriageAssistantResponse.model_validate(payload)
    except ValidationError as exc:
        detail = _first_error_detail(exc)
        reason = "cross_capability_fields" if "cross_capability_fields" in detail else "schema_validation_failed"
        return SchemaValidationResult(ok=False, degrade_reason=reason, detail=detail)
    data = model.model_dump(mode="python")
    data["advisory_only"] = True
    data["capability"] = "triage_assistant"
    # Soft-sanitize known forbidden triage phrases (intake must not claim completion).
    notice = str(data.get("intake_notice_draft") or "")
    hit = _contains_fabricated_facts(notice)
    if hit:
        return SchemaValidationResult(
            ok=False,
            degrade_reason="fabricated_completion_claim",
            detail=f"intake_notice_draft contains forbidden phrase: {hit}",
        )
    return SchemaValidationResult(ok=True, data=data)


def validate_handling_response(
    payload: Any,
    *,
    facts_sufficient: bool,
) -> SchemaValidationResult:
    """Validate handling_assistant payload. Blocks fabricated completion without facts."""
    if payload is None:
        return SchemaValidationResult(ok=False, degrade_reason="empty_payload", detail="payload is null")
    if not isinstance(payload, dict):
        return SchemaValidationResult(ok=False, degrade_reason="invalid_payload_type", detail="payload is not an object")
    try:
        model = HandlingAssistantResponse.model_validate(payload)
    except ValidationError as exc:
        detail = _first_error_detail(exc)
        reason = "cross_capability_fields" if "cross_capability_fields" in detail else "schema_validation_failed"
        return SchemaValidationResult(ok=False, degrade_reason=reason, detail=detail)

    data = model.model_dump(mode="python")
    data["advisory_only"] = True
    data["capability"] = "handling_assistant"
    # Force facts_sufficient from ticket truth, not model self-report.
    data["facts_sufficient"] = bool(facts_sufficient)

    if not facts_sufficient:
        draft = str(data.get("reply_draft") or "")
        template = str(data.get("reply_template") or "")
        plan_blob = json.dumps(data.get("handling_plan") or [], ensure_ascii=False)
        hit = (
            _contains_fabricated_facts(draft)
            or _contains_fabricated_facts(template)
            or _contains_fabricated_facts(plan_blob)
        )
        if hit:
            return SchemaValidationResult(
                ok=False,
                degrade_reason="fabricated_handling_facts",
                detail=f"unverified completion claim without handling facts: {hit}",
            )
        # Require placeholder-style draft when facts are insufficient.
        if "【" not in draft and draft.strip() and draft.strip() != template.strip():
            # Deterministic text without placeholders that asserts outcomes is unsafe.
            if any(tok in draft for tok in ("已", "完成", "修复", "办结")):
                return SchemaValidationResult(
                    ok=False,
                    degrade_reason="fabricated_handling_facts",
                    detail="reply_draft asserts outcomes without facts or placeholders",
                )
    return SchemaValidationResult(ok=True, data=data)


def _first_error_detail(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "validation_failed"
    err = errors[0]
    loc = ".".join(str(part) for part in err.get("loc", ()))
    msg = str(err.get("msg") or "invalid")
    # Pydantic wraps custom ValueError messages as "Value error, <msg>"
    if "cross_capability_fields:" in msg:
        return msg.split("Value error, ", 1)[-1].strip()
    return f"{loc}: {msg}" if loc else msg


# --- RAG citation post-validation -------------------------------------------------

_CITATION_REF_RE = re.compile(r"\[来源\s*(\d+)\s*\]")


def extract_citation_indices(text: str) -> list[int]:
    """Extract [来源N] indices from answer body (order preserved, deduped)."""
    seen: set[int] = set()
    ordered: list[int] = []
    for match in _CITATION_REF_RE.finditer(text or ""):
        idx = int(match.group(1))
        if idx not in seen:
            seen.add(idx)
            ordered.append(idx)
    return ordered


def validate_rag_citations(
    answer: str,
    citations: list[dict[str, Any]],
) -> SchemaValidationResult:
    """Ensure every [来源N] in answer exists in citations; require at least one when citations exist.

    Does not invent citations. On failure, caller must degrade to a conservative answer
    built from the original retrieval snippets.
    """
    valid_indices = {
        int(c["index"])
        for c in citations
        if isinstance(c, dict) and c.get("index") is not None
    }
    refs = extract_citation_indices(answer)
    if not citations:
        if refs:
            return SchemaValidationResult(
                ok=False,
                degrade_reason="citation_without_evidence",
                detail=f"answer cites sources {refs} but citations list is empty",
            )
        return SchemaValidationResult(ok=True, data={"answer": answer, "citations": []})

    invalid = [idx for idx in refs if idx not in valid_indices]
    if invalid:
        return SchemaValidationResult(
            ok=False,
            degrade_reason="citation_index_not_found",
            detail=f"answer cites non-existent sources: {invalid}; valid={sorted(valid_indices)}",
        )
    if not refs:
        return SchemaValidationResult(
            ok=False,
            degrade_reason="missing_citations",
            detail="retrieval returned evidence but answer has no [来源N] markers",
        )
    return SchemaValidationResult(
        ok=True,
        data={"answer": answer, "citations": citations, "cited_indices": refs},
    )


def build_conservative_rag_answer(citations: list[dict[str, Any]], *, reason: str) -> str:
    """Build a conservative answer from real retrieval excerpts with valid [来源N] markers."""
    if not citations:
        return (
            "检索结果引用校验未通过，且无可用原始片段。"
            f"（原因：{reason}）请人工查阅知识库或联系管理员。"
        )
    parts: list[str] = [
        "检索到相关资料，但模型回答的引用未通过校验；以下为基于原始检索片段的保守摘要，请人工核对：",
        "",
    ]
    for item in citations[:5]:
        idx = item.get("index")
        title = item.get("title") or "未命名文档"
        excerpt = (item.get("excerpt") or "").strip() or "（无摘要）"
        parts.append(f"[来源{idx}] {title}\n{excerpt}")
        parts.append("")
    parts.append(f"（注：已阻止不可信引用；降级原因：{reason}）")
    return "\n".join(parts).strip()
