import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from ..authorization import AuthorizationPolicy, Principal
from ..errors import BusinessError, PermissionDenied, TicketNotFound
from ..llm_client import get_llm_client
from ..logging_config import request_id_context
from ..models import AiSuggestionModel
from ..schemas import AiSuggestionRead, HotspotRead, PreReviewRequest, PreReviewResult
from .ai_usage_recorder import (
    AiUsageRecorder,
    make_context,
    CAP_AI_ANALYZE,
    CAP_PRE_REVIEW,
    CAP_TRIAGE_ASSISTANT,
    CAP_HANDLING_ASSISTANT,
)


SENSITIVE_WORDS = ("上访", "群体性", "暴恐", "爆炸", "自杀", "伤亡", "疫情", "邪教", "未成年人")
URGENT_WORDS = ("火灾", "燃气泄漏", "坍塌", "触电", "有人受伤", "生命危险", "立即", "紧急")
STOP_CHARS = set("，。！？；：、,.!?;: \t\r\n")
TRIAGE_FORBIDDEN = ("已经解决", "已经修复", "已完成维修", "已现场核查", "已派人", "已恢复正常", "已经办结")
HANDLING_FACT_FIELDS = (
    "resolution_summary", "resolution_measures", "resolution_outcome", "public_reply",
)
TRIAGE_STATUSES = frozenset({"pending", "accepted"})
HANDLING_STATUSES = frozenset({"assigned", "processing"})
QUALITY_DECISIONS = frozenset({"helpful", "not_helpful"})
ADOPT_DECISIONS = frozenset({"adopted", "adopted_with_edits", "rejected"})
DEFAULT_INTAKE_NOTICE = (
    "您的诉求已受理，平台将根据设施权属派发至相关责任部门，具体处理进度可通过工单号查询。"
)
PLACEHOLDER_REPLY = (
    "经现场核查，该设施位于【位置】，设施权属为【权属单位】。"
    "工作人员于【处理时间】采取【处理措施】，目前【处理状态】。"
)


class AiService:
    def __init__(self, repository, audit, settings):
        self.repository = repository
        self.audit = audit
        self.settings = settings

    @staticmethod
    def _fingerprint(ticket) -> str:
        value = "|".join(str(getattr(ticket, key, "") or "") for key in (
            "description", "location", "event", "occurred_at_text", "target", "contact",
            "category_id", "resolution_summary", "resolution_measures", "resolution_outcome", "public_reply",
        ))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _tokens(text: str) -> set[str]:
        normalized = "".join(ch.lower() for ch in text if ch not in STOP_CHARS)
        if len(normalized) < 2:
            return {normalized} if normalized else set()
        return {normalized[index:index + 2] for index in range(len(normalized) - 1)}

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        a, b = cls._tokens(left), cls._tokens(right)
        return len(a & b) / len(a | b) if a and b else 0.0

    @staticmethod
    def _present(item: AiSuggestionModel) -> AiSuggestionRead:
        return AiSuggestionRead(
            id=item.id, ticket_id=item.ticket_id, suggestion_type=item.suggestion_type,
            status=item.status, risk_level=item.risk_level, confidence=item.confidence,
            provider=item.provider, model_name=item.model_name, result=json.loads(item.result_json),
            explanation=item.explanation, review_decision=item.review_decision,
            review_comment=item.review_comment, reviewed_at=item.reviewed_at, created_at=item.created_at,
        )

    def _ticket(self, ticket_id: str, principal: Principal):
        ticket = self.repository.ticket(ticket_id)
        if not ticket:
            raise TicketNotFound(ticket_id)
        AuthorizationPolicy.require_view(principal, ticket)
        return ticket

    def _assignment(self, ticket):
        history = self.repository.assignment_history(ticket.category_id, ticket.location)
        counts = Counter(item.assigned_department_id for item in history if item.assigned_department_id)
        if ticket.category and ticket.category.default_department_id:
            counts[ticket.category.default_department_id] += 5
        departments = {item.id: item for item in self.repository.active_departments()}
        ranked = [(department_id, score) for department_id, score in counts.most_common(3) if department_id in departments]
        if not ranked and departments:
            ranked = [(next(iter(departments)), 1)]
        total = sum(score for _, score in ranked) or 1
        return {
            "recommended_departments": [
                {"department_id": department_id, "department_name": departments[department_id].name,
                 "score": round(score / total, 3), "historical_cases": max(0, score - 5)}
                for department_id, score in ranked
            ],
            "factors": ["末级分类默认责任部门", "同分类历史办结工单", "诉求地点"],
            "requires_human_confirmation": True,
        }, 78 if ranked else 25

    def _similar(self, ticket):
        base = f"{ticket.description} {ticket.location} {ticket.event or ''}"
        matches = []
        for item in self.repository.candidates(ticket.ticket_id):
            score = self._similarity(base, f"{item.description} {item.location} {item.event or ''}")
            if score >= 0.22:
                matches.append({
                    "ticket_id": item.ticket_id, "score": round(score, 3),
                    "duplicate_likelihood": "high" if score >= 0.72 else "possible",
                    "status": item.status,
                })
        matches.sort(key=lambda item: item["score"], reverse=True)
        return {"matches": matches[:10], "possible_duplicate": bool(matches and matches[0]["score"] >= 0.72)}, min(96, int((matches[0]["score"] if matches else .25) * 100))

    @staticmethod
    def _summary(ticket):
        text = re.sub(r"\s+", " ", ticket.description).strip()
        summary = text if len(text) <= 120 else text[:117] + "…"
        impact = "周边居民" if any(w in text for w in ("路灯", "照明", "道路", "垃圾", "噪音", "施工")) else "当事人"
        urgency = "影响居民基本生活" if any(w in text for w in ("路灯", "停水", "停电", "燃气", "火灾")) else "存在安全隐患" if any(w in text for w in ("坑洼", "破损", "泄漏", "裸露")) else "一般性诉求"
        return {"summary": f"{ticket.request_type}：{summary}", "location": ticket.location, "impact": f"影响{impact}正常生活", "urgency_hint": urgency, "editable": True}, 82

    @staticmethod
    def _completeness(ticket):
        missing, warnings, tips = [], [], []
        if len(ticket.description.strip()) < 12:
            missing.append("详细诉求描述")
            tips.append("建议补充具体问题现象、持续时间、影响范围")
        if not ticket.location or ticket.location.strip() in {"未知", "线上", "不清楚"}:
            missing.append("可定位的具体地点")
            tips.append("具体到路名、门牌号或显著地标，便于工作人员现场核查")
        if not ticket.occurred_at_text and not ticket.occurred_at_start:
            missing.append("发生时间")
            tips.append("包括首次发现时间和持续时长")
        if not ticket.contact:
            warnings.append("未留联系方式，可能影响补充核实和回访")
        if not ticket.target:
            warnings.append("未明确涉及对象，建议补充责任单位或相关方")
        recommendation = "信息完整，可进入人工受理核验" if not missing else f"建议先请市民补充：{'、'.join(missing)}"
        return {"complete": not missing, "missing_fields": missing, "warnings": warnings,
                "tips": tips, "recommendation": recommendation}, 92

    @staticmethod
    def _document(ticket):
        summary = ticket.resolution_summary or "经核查，相关诉求正在办理。"
        measures = ticket.resolution_measures or "承办部门将依据职责开展核查处置，并及时反馈进展。"
        outcome = ticket.public_reply or "感谢您对政务服务工作的监督与支持。"
        return {
            "title": f"关于工单 {ticket.ticket_id} 的处理答复（AI草稿）",
            "body": f"您好：\n您反映的“{ticket.description[:80]}”事项已收悉。{summary}\n处理情况：{measures}\n{outcome}",
            "requires_fact_check": True,
            "prohibited_use": "不得未经人工核实直接作为办结、拒绝或其他行政决定文书发送",
        }, 70 if ticket.resolution_summary else 45

    @staticmethod
    def _risk(ticket):
        text = f"{ticket.description} {ticket.event or ''} {ticket.location}"
        urgent = [word for word in URGENT_WORDS if word in text]
        sensitive = [word for word in SENSITIVE_WORDS if word in text]
        infra_signals = [w for w in ("路灯", "照明", "停水", "停电", "燃气", "电梯", "井盖", "坑洼", "破损") if w in text]
        level = "urgent" if urgent else "sensitive" if sensitive or infra_signals else "none"
        if urgent:
            recommendation = "请立即由人工核实并按应急预案升级，建议 2 小时内响应，同时通知属地街道和主管部门"
        elif infra_signals:
            recommendation = f"涉及市政基础设施问题（{'、'.join(infra_signals)}），建议优先派发市政/物业主管部门，24小时内现场核查，并设置临时安全提示"
        elif sensitive:
            recommendation = "请由有权限人员重点核实，建议专人跟踪并在规定时限内反馈"
        else:
            recommendation = "未发现规则库中的敏感或紧急信号，按正常流程受理即可"
        return {"level": level, "matched_signals": urgent + sensitive + infra_signals,
                "recommendation": recommendation,
                "time_limit_hint": "2小时内响应" if urgent else "24小时内核查" if infra_signals else "正常时限",
                "automatic_decision": False}, 95 if urgent or sensitive else 78 if infra_signals else 62

    @staticmethod
    def _handling_facts_sufficient(ticket) -> bool:
        filled = [
            bool((getattr(ticket, key, None) or "").strip())
            for key in ("resolution_summary", "resolution_measures", "public_reply")
        ]
        return sum(1 for item in filled if item) >= 2

    def _triage_bundle(self, ticket):
        summary_payload, _ = self._summary(ticket)
        completeness_payload, completeness_score = self._completeness(ticket)
        risk_payload, _ = self._risk(ticket)
        assignment_payload, assignment_score = self._assignment(ticket)
        urgency_level = "urgent" if risk_payload["level"] == "urgent" else (
            "expedited" if risk_payload["level"] == "sensitive" else "normal"
        )
        departments = {
            "recommended_departments": [
                {
                    "department_id": row.get("department_id"),
                    "department_name": row.get("department_name"),
                    "recommendation_level": "high" if index == 0 else "medium",
                    "reason": "基于分类默认责任部门与历史办结分布",
                    "historical_cases": row.get("historical_cases"),
                    "score": row.get("score"),
                }
                for index, row in enumerate(assignment_payload.get("recommended_departments") or [])
            ]
        }
        notice = DEFAULT_INTAKE_NOTICE
        payload = {
            "capability": CAP_TRIAGE_ASSISTANT,
            "case_summary": {
                "description": summary_payload.get("summary"),
                "location": summary_payload.get("location") or ticket.location,
                "duration": ticket.occurred_at_text or "未提供",
                "affected_scope": summary_payload.get("impact"),
            },
            "classification": {
                "request_type": ticket.request_type or "待确认",
                "category": ticket.category.name if ticket.category else "待确认",
                "subcategory": "",
                "reason": "基于诉求描述与现有分类配置生成，需坐席确认",
            },
            "urgency": {
                "level": urgency_level,
                "emergency": risk_payload["level"] == "urgent",
                "reason": risk_payload.get("recommendation") or summary_payload.get("urgency_hint"),
            },
            "completeness": {
                "complete": completeness_payload.get("complete"),
                "known_fields": [f for f in ("description", "location", "occurred_at_text", "contact") if getattr(ticket, f, None)],
                "missing_fields": completeness_payload.get("missing_fields") or [],
                "follow_up_questions": completeness_payload.get("tips") or [],
                "completeness_score": completeness_score,
            },
            "department_candidates": departments["recommended_departments"],
            "sla_recommendation": {
                "response_deadline": risk_payload.get("time_limit_hint") or "按分类默认受理时限",
                "handling_deadline": "按分类默认办理时限（需人工确认）",
                "reason": "仅作受理阶段参考，不构成对市民的办结承诺",
            },
            "intake_notice_draft": notice,
            "advisory_only": True,
            "confidence_labels": {
                "completeness_score": completeness_score,
                "assignment_score": assignment_score,
            },
        }
        return self._sanitize_triage_payload(payload), None

    def _handling_bundle(self, ticket):
        facts_ok = self._handling_facts_sufficient(ticket)
        missing = []
        if not (ticket.resolution_summary or "").strip():
            missing.append("核查结果/处理摘要")
        if not (ticket.resolution_measures or "").strip():
            missing.append("处理措施")
        if not (ticket.public_reply or "").strip():
            missing.append("对市民回复要点")
        if not (ticket.resolution_outcome or "").strip():
            missing.append("当前处理结果")
        dept_name = ticket.department.name if getattr(ticket, "department", None) else "本部门"
        checklist = [
            "核实具体位置与门牌/杆号",
            "确认设施权属单位",
            "现场查看损坏程度与安全风险",
            "记录核查时间与工作人员",
            "留存现场照片或视频证据",
        ]
        plan = [
            "按核查清单完成现场核实",
            "明确主办与协办职责",
            "实施处置并记录措施与时间",
            "整理证据材料后起草回复",
            "提交办理结果供坐席复核办结",
        ]
        reply_template = PLACEHOLDER_REPLY
        reply_draft = reply_template if not facts_ok else (
            f"您好：您反映的“{(ticket.description or '')[:80]}”事项，"
            f"{ticket.resolution_summary or ''}。"
            f"处理措施：{ticket.resolution_measures or ''}。"
            f"{ticket.public_reply or ''}"
        )
        payload = {
            "capability": CAP_HANDLING_ASSISTANT,
            "case_summary": {
                "description": (ticket.description or "")[:200],
                "assigned_department": dept_name,
                "classification": ticket.category.name if ticket.category else "未分类",
                "known_facts": [
                    item for item in [
                        ticket.resolution_summary, ticket.resolution_measures, ticket.public_reply,
                    ] if item
                ],
            },
            "verification_checklist": checklist,
            "handling_plan": plan,
            "policy_references": ["按部门职责与现行公开政策规范办理；具体条文以知识库检索结果为准"],
            "risk_warnings": [
                "临近 SLA 截止时优先现场核查并留痕",
                "跨权属争议需书面确认后再处置",
            ],
            "missing_handling_facts": missing,
            "collaboration_suggestions": ["如权属不清，先联系综合受理窗口协调"],
            "evidence_checklist": ["现场照片", "核查记录", "处置前后对比材料"],
            "reply_template": reply_template,
            "reply_draft": reply_draft,
            "facts_sufficient": facts_ok,
            "advisory_only": True,
        }
        if not facts_ok:
            lowered = reply_draft
            for phrase in TRIAGE_FORBIDDEN:
                if phrase in lowered:
                    payload["reply_draft"] = reply_template
                    break
        return payload, None

    @staticmethod
    def _sanitize_triage_payload(payload: dict) -> dict:
        blob = json.dumps(payload, ensure_ascii=False)
        for phrase in TRIAGE_FORBIDDEN:
            if phrase in blob:
                payload["intake_notice_draft"] = DEFAULT_INTAKE_NOTICE
                payload["sla_recommendation"] = {
                    **(payload.get("sla_recommendation") or {}),
                    "reason": "已清除疑似办结承诺表述；SLA 仅供内部受理参考",
                }
                break
        notice = str(payload.get("intake_notice_draft") or "")
        for phrase in TRIAGE_FORBIDDEN:
            notice = notice.replace(phrase, "")
        payload["intake_notice_draft"] = notice.strip() or DEFAULT_INTAKE_NOTICE
        payload["advisory_only"] = True
        return payload

    def _require_triage_access(self, ticket, principal: Principal):
        if principal.role not in {"agent", "admin"}:
            raise PermissionDenied("仅坐席或管理员可使用智能分诊")
        if ticket.status not in TRIAGE_STATUSES:
            raise BusinessError(
                "INVALID_TICKET_STATE",
                f"智能分诊仅适用于 pending/accepted，当前状态为 {ticket.status}",
                409,
            )

    def _require_handling_access(self, ticket, principal: Principal):
        if principal.role not in {"department_staff", "admin"}:
            raise PermissionDenied("仅责任部门人员或管理员可使用办件助手")
        if ticket.status not in HANDLING_STATUSES:
            raise BusinessError(
                "INVALID_TICKET_STATE",
                f"办件助手仅适用于 assigned/processing，当前状态为 {ticket.status}",
                409,
            )
        if principal.role == "department_staff":
            if principal.department_id is None or ticket.assigned_department_id != principal.department_id:
                raise PermissionDenied("只能对本部门已派发工单使用办件助手")

    def analyze(self, ticket_id: str, types: list[str], principal: Principal, capability: str | None = None):
        ticket = self._ticket(ticket_id, principal)
        # Role capability defaults — agent triage vs department handling.
        if capability == CAP_TRIAGE_ASSISTANT or (
            capability is None and principal.role in {"agent", "admin"} and set(types) <= {
                CAP_TRIAGE_ASSISTANT, "assignment", "summary", "completeness", "risk", "similarity",
            } and CAP_TRIAGE_ASSISTANT in types
        ):
            self._require_triage_access(ticket, principal)
            types = [CAP_TRIAGE_ASSISTANT]
            usage_cap = CAP_TRIAGE_ASSISTANT
        elif capability == CAP_HANDLING_ASSISTANT or (
            capability is None and principal.role == "department_staff"
        ) or CAP_HANDLING_ASSISTANT in types:
            self._require_handling_access(ticket, principal)
            types = [CAP_HANDLING_ASSISTANT]
            usage_cap = CAP_HANDLING_ASSISTANT
        elif principal.role == "citizen":
            allowed = {"completeness", "summary", "similarity", "risk"}
            if not set(types) <= allowed:
                raise PermissionDenied("当前角色不能生成所请求的 AI 建议类型")
            usage_cap = CAP_AI_ANALYZE
        elif principal.role in {"agent", "admin"}:
            # Legacy granular types for agent: strip document_draft; prefer triage statuses.
            if "document_draft" in types:
                raise PermissionDenied("坐席分诊不得生成处理文书草稿，请使用 triage_assistant")
            if ticket.status not in TRIAGE_STATUSES and set(types) & {"assignment", "summary", "completeness", "risk"}:
                raise BusinessError(
                    "INVALID_TICKET_STATE",
                    f"受理分派类建议仅适用于 pending/accepted，当前状态为 {ticket.status}",
                    409,
                )
            allowed = {"assignment", "similarity", "summary", "completeness", "risk", CAP_TRIAGE_ASSISTANT}
            if not set(types) <= allowed:
                raise PermissionDenied("当前角色不能生成所请求的 AI 建议类型")
            usage_cap = CAP_AI_ANALYZE if CAP_TRIAGE_ASSISTANT not in types else CAP_TRIAGE_ASSISTANT
        else:
            raise PermissionDenied("当前角色不能生成 AI 建议")

        fingerprint = self._fingerprint(ticket)
        builders = {
            "assignment": self._assignment, "similarity": self._similar,
            "summary": self._summary, "completeness": self._completeness,
            "document_draft": self._document, "risk": self._risk,
            CAP_TRIAGE_ASSISTANT: self._triage_bundle,
            CAP_HANDLING_ASSISTANT: self._handling_bundle,
        }
        llm_types = {"summary", "document_draft", "risk", "assignment", CAP_TRIAGE_ASSISTANT, CAP_HANDLING_ASSISTANT}
        llm = get_llm_client()
        request_id = request_id_context.get() or uuid4().hex
        recorder = AiUsageRecorder(getattr(self.repository, "db", None))
        result = []
        for suggestion_type in dict.fromkeys(types):
            existing = self.repository.existing(ticket.ticket_id, suggestion_type, fingerprint)
            if existing:
                result.append(self._present(existing))
                continue
            provider = self.settings.ai_provider
            model_name = self.settings.ai_model_name
            payload = None
            confidence = 0
            prompt_version = None
            latency_ms = 0
            used_llm = False
            if suggestion_type in llm_types and llm.available:
                context = self._llm_context(ticket, suggestion_type)
                llm_result = llm.complete(suggestion_type, context)
                recorder.record_llm_call(
                    make_context(usage_cap, route=usage_cap,
                                 principal=principal, request_id=request_id),
                    llm_result, provider=llm.provider,
                    degraded=not llm_result.success,
                    degrade_reason="llm_call_failed" if not llm_result.success else None,
                )
                if llm_result.success and llm_result.data:
                    payload = llm_result.data
                    provider = "deepseek"
                    model_name = llm_result.model
                    prompt_version = llm_result.prompt_version
                    latency_ms = llm_result.latency_ms
                    confidence = 0  # model self-score is not a reliable metric
                    used_llm = True
                    if suggestion_type == CAP_TRIAGE_ASSISTANT:
                        payload = self._sanitize_triage_payload(payload)
                    if suggestion_type == CAP_HANDLING_ASSISTANT and not self._handling_facts_sufficient(ticket):
                        payload["facts_sufficient"] = False
                        payload["reply_draft"] = payload.get("reply_template") or PLACEHOLDER_REPLY
                        payload["missing_handling_facts"] = payload.get("missing_handling_facts") or [
                            "核查结果/处理摘要", "处理措施", "对市民回复要点",
                        ]
            if payload is None:
                if suggestion_type in llm_types:
                    recorder.record_rules_call(
                        make_context(usage_cap, route=usage_cap,
                                     principal=principal, request_id=request_id),
                        model_name="rules",
                        degrade_reason="rules_fallback" if llm.available else "llm_unavailable",
                    )
                built = builders[suggestion_type](ticket)
                payload, confidence = built[0], built[1]
                if confidence is None:
                    confidence = 0
            risk_level = payload.get("level", "attention" if payload.get("possible_duplicate") else "none")
            if suggestion_type in {CAP_TRIAGE_ASSISTANT, CAP_HANDLING_ASSISTANT}:
                urgency = (payload.get("urgency") or {})
                risk_level = "urgent" if urgency.get("emergency") else "attention"
            explanation = (
                f"由 {model_name} 生成（capability={usage_cap}），仅供人工参考，不会自动变更工单状态。"
                if used_llm
                else f"基于规则与可见工单数据生成（capability={usage_cap}）；结果仅供人工参考。"
            )
            item = AiSuggestionModel(
                id=str(uuid4()), ticket_id=ticket.ticket_id, suggestion_type=suggestion_type,
                status="completed", risk_level=risk_level if isinstance(risk_level, str) else "none",
                confidence=int(confidence or 0),
                provider=provider, model_name=model_name,
                input_fingerprint=fingerprint, result_json=json.dumps(payload, ensure_ascii=False),
                explanation=explanation,
                generated_by_user_id=principal.user_id,
                created_at=datetime.now(timezone.utc),
            )
            result.append(self._present(self.repository.add(item)))
            self.audit.log(principal, "generate_ai_suggestion", resource_type="ai_suggestion", resource_id=item.id,
                           details={"ticket_id": ticket.ticket_id, "suggestion_type": suggestion_type,
                                    "capability": usage_cap,
                                    "provider": provider, "model": model_name, "prompt_version": prompt_version,
                                    "latency_ms": latency_ms, "advisory_only": True})
        return result

    def _llm_context(self, ticket, suggestion_type: str) -> dict:
        """Build context dict for LLM prompt."""
        departments = [d.name for d in self.repository.active_departments()]
        assigned = ticket.department.name if getattr(ticket, "department", None) else "未派发"
        return {
            "ticket_id": ticket.ticket_id,
            "status": ticket.status or "",
            "request_type": ticket.request_type or "未指定",
            "description": ticket.description or "",
            "location": ticket.location or "未知",
            "event": ticket.event or "",
            "occurred_at_text": ticket.occurred_at_text or "未提供",
            "priority": ticket.priority or "normal",
            "category_name": ticket.category.name if ticket.category else "未分类",
            "resolution_summary": ticket.resolution_summary or "暂无",
            "resolution_measures": ticket.resolution_measures or "暂无",
            "public_reply": ticket.public_reply or "暂无",
            "departments": "、".join(departments) if departments else "无可用部门",
            "assigned_department": assigned,
            "facts_sufficient": "是" if self._handling_facts_sufficient(ticket) else "否",
        }

    def list(self, ticket_id: str, principal: Principal):
        self._ticket(ticket_id, principal)
        items = self.repository.list_for_ticket(ticket_id)
        if principal.role == "citizen":
            items = [item for item in items if item.suggestion_type in {"completeness", "summary", "similarity", "risk"}]
        elif principal.role == "agent":
            items = [item for item in items if item.suggestion_type in {
                CAP_TRIAGE_ASSISTANT, "assignment", "summary", "completeness", "risk", "similarity",
            }]
        elif principal.role == "department_staff":
            items = [item for item in items if item.suggestion_type in {
                CAP_HANDLING_ASSISTANT, "ticket_advice", "document_draft",
            }]
        return [self._present(item) for item in items]

    def review(self, suggestion_id: str, decision: str, comment: str | None, principal: Principal,
               edited_content: dict | None = None):
        item = self.repository.get(suggestion_id)
        if not item:
            raise BusinessError("AI_SUGGESTION_NOT_FOUND", "未找到 AI 建议", 404)
        ticket = self._ticket(item.ticket_id, principal)
        status_before = ticket.status
        if decision in QUALITY_DECISIONS:
            action = "review_ai_suggestion_quality"
        elif decision in ADOPT_DECISIONS:
            action = "review_ai_suggestion_adoption"
            if item.suggestion_type == CAP_TRIAGE_ASSISTANT:
                self._require_triage_access(ticket, principal)
            elif item.suggestion_type == CAP_HANDLING_ASSISTANT:
                self._require_handling_access(ticket, principal)
        else:
            raise BusinessError("INVALID_REVIEW_DECISION", "不支持的审核决策", 422)
        item.review_decision = decision
        item.review_comment = comment
        item.reviewed_by_user_id = principal.user_id
        item.reviewed_at = datetime.now(timezone.utc)
        if edited_content and decision == "adopted_with_edits":
            # Snapshot edited content into comment/result metadata without mutating ticket status.
            merged = json.loads(item.result_json)
            merged["edited_content"] = edited_content
            item.result_json = json.dumps(merged, ensure_ascii=False)
        item = self.repository.save(item)
        self.audit.log(principal, action, resource_type="ai_suggestion", resource_id=item.id,
                       details={
                           "decision": decision,
                           "ticket_id": item.ticket_id,
                           "suggestion_type": item.suggestion_type,
                           "ticket_status_unchanged": ticket.status,
                           "status_before": status_before,
                       })
        # Re-load ticket to assert status was not mutated by AI review.
        refreshed = self.repository.ticket(item.ticket_id)
        if refreshed and refreshed.status != status_before:
            raise BusinessError("AI_MUST_NOT_MUTATE_STATUS", "AI 建议审核不得变更工单状态", 500)
        return self._present(item)

    def hotspots(self, principal: Principal, days: int):
        if principal.role not in {"agent", "department_staff", "admin"}:
            raise PermissionDenied()
        groups = defaultdict(list)
        for ticket in self.repository.hotspot_rows(principal, days):
            location = re.split(r"[路街道镇乡社区小区号]", ticket.location or "未知地点", maxsplit=1)[0][:12] or "未知地点"
            key = f"{ticket.category_id or 'unclassified'}:{location}"
            groups[key].append(ticket)
        rows = []
        for key, tickets in groups.items():
            if len(tickets) < 2:
                continue
            urgent_count = sum(1 for ticket in tickets if ticket.priority in {"urgent", "major"})
            category = tickets[0].category.name if getattr(tickets[0], "category", None) else "未分类诉求"
            rows.append(HotspotRead(cluster_key=key, label=f"{category} · {tickets[0].location[:18]}", count=len(tickets),
                                    urgent_count=urgent_count, sample_ticket_ids=[ticket.ticket_id for ticket in tickets[:5]]))
        rows.sort(key=lambda item: (item.count, item.urgent_count), reverse=True)
        self.audit.log(principal, "view_ai_hotspots", resource_type="ai_hotspot", details={"days": days, "clusters": len(rows)})
        return rows[:50]

    def pre_review(self, payload: PreReviewRequest, principal: Principal) -> PreReviewResult:
        """Stateless pre-submission review: identify fields, check completeness, normalize, recommend department."""
        description = payload.description.strip()
        location = (payload.location or "").strip()
        occurred_at_text = (payload.occurred_at_text or "").strip()
        target = (payload.target or "").strip()
        request_type = (payload.request_type or "").strip()

        # --- Try LLM first ---
        provider = "rules"
        llm = get_llm_client()
        request_id = request_id_context.get() or uuid4().hex
        recorder = AiUsageRecorder(getattr(self.repository, "db", None))
        identified_type = request_type or "投诉"
        identified_location = location or "未提供"
        identified_time = occurred_at_text or "未提供"
        identified_target = target or "未提供"
        impact = "待评估"
        urgency_hint = "一般性诉求"
        normalized_description = description if len(description) <= 200 else description[:197] + "…"

        if llm.available:
            context = {
                "description": description,
                "request_type": request_type or "未指定",
                "location": location or "未提供",
                "occurred_at_text": occurred_at_text or "未提供",
                "target": target or "未提供",
            }
            llm_result = llm.complete("pre_review", context)
            # P0-D: record every pre-review LLM call with real usage
            recorder.record_llm_call(
                make_context(CAP_PRE_REVIEW, route="pre_review",
                             principal=principal, request_id=request_id),
                llm_result, provider=llm.provider,
                degraded=not llm_result.success,
                degrade_reason="llm_call_failed" if not llm_result.success else None,
            )
            if llm_result.success and llm_result.data:
                data = llm_result.data
                provider = "deepseek"
                identified_type = data.get("identified_type", identified_type)
                identified_location = data.get("identified_location", identified_location)
                identified_time = data.get("identified_time", identified_time)
                identified_target = data.get("identified_target", identified_target)
                impact = data.get("impact", impact)
                urgency_hint = data.get("urgency_hint", urgency_hint)
                normalized_description = data.get("normalized_description", normalized_description)
        else:
            # LLM unavailable: record rules-tier path honestly
            recorder.record_rules_call(
                make_context(CAP_PRE_REVIEW, route="pre_review",
                             principal=principal, request_id=request_id),
                model_name="rules",
                degrade_reason="llm_unavailable",
            )

        # --- Rule-based fallback / enrichment ---
        if provider == "rules":
            # Type detection
            if not request_type:
                if any(w in description for w in ("投诉", "举报", "不满", "差")):
                    identified_type = "投诉"
                elif any(w in description for w in ("建议", "希望", "应该", "改进")):
                    identified_type = "建议"
                elif any(w in description for w in ("咨询", "请问", "如何", "怎么", "政策")):
                    identified_type = "咨询"
                elif any(w in description for w in ("求助", "帮忙", "困难", "紧急")):
                    identified_type = "求助"
            # Urgency
            infra_words = ("路灯", "照明", "停水", "停电", "燃气", "电梯", "井盖", "坑洼", "破损", "泄漏")
            danger_words = ("火灾", "坍塌", "触电", "有人受伤", "生命危险")
            if any(w in description for w in danger_words):
                urgency_hint = "影响居民基本生活"
            elif any(w in description for w in infra_words):
                urgency_hint = "存在安全隐患"
            # Impact
            if any(w in description for w in ("路灯", "照明", "道路", "垃圾", "噪音", "施工", "停水", "停电")):
                impact = "影响周边居民正常生活"
            elif any(w in description for w in ("小区", "社区", "楼栋", "单元")):
                impact = "影响小区居民"
            else:
                impact = "影响当事人"
            # Normalized
            type_label = identified_type
            loc_part = f"，位于{identified_location}" if identified_location != "未提供" else ""
            time_part = f"，发生于{identified_time}" if identified_time != "未提供" else ""
            normalized_description = f"市民{type_label}：{description[:150]}{loc_part}{time_part}。"

        # Validate type
        if identified_type not in {"投诉", "建议", "咨询", "求助"}:
            identified_type = "投诉"

        # --- Completeness check ---
        missing_fields: list[str] = []
        field_tips: dict[str, str] = {}
        if len(description) < 12:
            missing_fields.append("详细诉求描述")
            field_tips["详细诉求描述"] = "建议补充具体问题现象、持续时间、影响范围"
        if not location:
            missing_fields.append("具体地点")
            field_tips["具体地点"] = "具体到路名、门牌号或显著地标，便于工作人员现场核查"
        if not occurred_at_text:
            missing_fields.append("发生时间")
            field_tips["发生时间"] = "包括首次发现时间和持续时长"
        if not target:
            missing_fields.append("涉及对象")
            field_tips["涉及对象"] = "填写责任单位、相关方或具体设施"

        # --- Department recommendation ---
        recommended_department = None
        department_reason = None
        departments = self.repository.active_departments()
        if departments:
            # Simple keyword-based matching for pre-review (no ticket exists yet)
            dept_keywords = {
                "市政": ("路灯", "照明", "道路", "坑洼", "井盖", "市政", "排水"),
                "环保": ("垃圾", "噪音", "污染", "废水", "废气", "环保"),
                "住建": ("小区", "物业", "楼栋", "电梯", "房屋", "住建"),
                "公安": ("治安", "交通", "火灾", "报警", "公安"),
                "民政": ("低保", "救助", "养老", "残疾", "民政"),
                "教育": ("学校", "教育", "培训", "入学"),
                "卫健": ("医院", "医疗", "健康", "疫情", "卫生"),
            }
            best_dept = None
            best_score = 0
            for dept in departments:
                score = 0
                for keyword_group, keywords in dept_keywords.items():
                    if keyword_group in dept.name:
                        score += sum(1 for kw in keywords if kw in description)
                if score > best_score:
                    best_score = score
                    best_dept = dept
            if best_dept and best_score > 0:
                recommended_department = best_dept.name
                department_reason = f"诉求内容涉及{best_dept.name}职责范围"
            elif departments:
                # Fallback to first active department (general intake)
                recommended_department = departments[0].name
                department_reason = "建议由综合受理窗口统一分派"

        return PreReviewResult(
            identified_type=identified_type,
            identified_location=identified_location,
            identified_time=identified_time,
            identified_target=identified_target,
            impact=impact,
            urgency_hint=urgency_hint,
            missing_fields=missing_fields,
            field_tips=field_tips,
            normalized_description=normalized_description,
            recommended_department=recommended_department,
            department_reason=department_reason,
            provider=provider,
        )

    def case_advice(self, ticket_id: str, principal: Principal) -> dict:
        """Generate AI case handling advice for department staff. Advisory only.

        Delegates to KB-powered ticket_advice so advice is grounded in the RAG
        knowledge base with citations. Falls back to rules if KB unavailable.
        """
        from ..authorization import AuthorizationPolicy
        from ..errors import PermissionDenied, TicketNotFound
        ticket = self.repository.ticket(ticket_id)
        if not ticket:
            raise TicketNotFound(ticket_id)
        AuthorizationPolicy.require_view(principal, ticket)
        if principal.role not in {"department_staff", "agent", "admin"}:
            raise PermissionDenied("只有工作人员可以使用 AI 办件助手")
        request_id = request_id_context.get() or uuid4().hex
        try:
            from ..services.kb_service import KnowledgeBaseService
            from ..database import SessionLocal
            # Use a fresh session so the KB service manages its own transaction
            with SessionLocal() as kb_db:
                kb_service = KnowledgeBaseService(kb_db)
                advice = kb_service.ticket_advice(
                    ticket, principal, request_id=request_id,
                )
                kb_db.commit()
            self.audit.log(
                principal, "ai_case_advice",
                resource_type="ticket", resource_id=ticket_id,
                details={"provider": advice.get("provider"),
                         "no_evidence": advice.get("no_evidence"),
                         "source": "kb_rag"},
            )
            return advice
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("KB ticket_advice failed: %s", exc)
        # Last-resort fallback: rule-based advice (no citations).
        # P0-D: record rules-tier fallback honestly.
        recorder = AiUsageRecorder(getattr(self.repository, "db", None))
        recorder.record_rules_call(
            make_context("ticket_advice", route="ticket_advice",
                         principal=principal, request_id=request_id),
            model_name="rules-fallback",
            degrade_reason="kb_unavailable",
        )
        description = ticket.description or ""
        category_name = ticket.category.name if getattr(ticket, "category", None) else "未分类"
        advice = {
            "applicable_policies": ["请查阅本部门相关制度文件"],
            "verification_needed": ["核实市民描述的事实是否属实", "确认涉及的具体位置和责任方"],
            "material_completeness": "市民提交信息基本完整" if len(description) > 20 else "描述较简略，建议联系市民补充",
            "suggested_steps": ["核实事实现场情况", "联系相关责任方", "形成处理意见", "撰写公开答复", "提交处理结果"],
            "responsibility_boundary": f"本工单属于{category_name}类别，请在本部门职责范围内处理。如涉及其他部门，建议申请协办。",
            "timeline_risk": "请在SLA时限内完成处理，避免超时。",
            "similar_cases": [],
            "reply_draft": f"您好，您反映的“{description[:50]}”事项已收悉。我部门将尽快核实处理，并及时反馈结果。感谢您的监督与支持。",
            "citations": [],
            "no_evidence": True,
            "provider": "rules",
            "model": "rules-fallback",
            "advisory_only": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            from ..services.kb_service import KnowledgeBaseService
            from ..database import SessionLocal
            with SessionLocal() as kb_db:
                advice = KnowledgeBaseService(kb_db)._persist_ticket_advice(ticket, principal, advice)
                kb_db.commit()
        except Exception:
            advice_id = str(uuid4())
            advice["advice_id"] = advice_id
        return advice
