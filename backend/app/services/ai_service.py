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
)


SENSITIVE_WORDS = ("上访", "群体性", "暴恐", "爆炸", "自杀", "伤亡", "疫情", "邪教", "未成年人")
URGENT_WORDS = ("火灾", "燃气泄漏", "坍塌", "触电", "有人受伤", "生命危险", "立即", "紧急")
STOP_CHARS = set("，。！？；：、,.!?;: \t\r\n")


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

    def analyze(self, ticket_id: str, types: list[str], principal: Principal):
        ticket = self._ticket(ticket_id, principal)
        allowed = {"completeness", "summary", "similarity", "risk"} if principal.role == "citizen" else {
            "assignment", "similarity", "summary", "completeness", "document_draft", "risk"
        }
        if not set(types) <= allowed:
            raise PermissionDenied("当前角色不能生成所请求的 AI 建议类型")
        fingerprint = self._fingerprint(ticket)
        builders = {
            "assignment": self._assignment, "similarity": self._similar,
            "summary": self._summary, "completeness": self._completeness,
            "document_draft": self._document, "risk": self._risk,
        }
        # Types that can be enhanced by LLM
        llm_types = {"summary", "document_draft", "risk", "assignment"}
        llm = get_llm_client()
        request_id = request_id_context.get() or uuid4().hex
        recorder = AiUsageRecorder(getattr(self.repository, "db", None))
        result = []
        for suggestion_type in dict.fromkeys(types):
            existing = self.repository.existing(ticket.ticket_id, suggestion_type, fingerprint)
            if existing:
                result.append(self._present(existing))
                continue
            # Try LLM first for supported types, fall back to rules
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
                # P0-D: record every LLM call (success or failure) with real usage
                recorder.record_llm_call(
                    make_context(CAP_AI_ANALYZE, route="ai_analyze",
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
                    confidence = 88
                    used_llm = True
            # Fallback to rules — record rules-tier usage honestly (zero tokens)
            if payload is None:
                if suggestion_type in llm_types:
                    recorder.record_rules_call(
                        make_context(CAP_AI_ANALYZE, route="ai_analyze",
                                     principal=principal, request_id=request_id),
                        model_name="rules",
                        degrade_reason="rules_fallback" if llm.available else "llm_unavailable",
                    )
                payload, confidence = builders[suggestion_type](ticket)
            risk_level = payload.get("level", "attention" if payload.get("possible_duplicate") else "none")
            explanation = (
                f"由 {model_name} 生成，仅供人工参考。"
                if used_llm
                else "基于当前工单、分类配置与可见历史工单生成；结果仅供人工参考。"
            )
            item = AiSuggestionModel(
                id=str(uuid4()), ticket_id=ticket.ticket_id, suggestion_type=suggestion_type,
                status="completed", risk_level=risk_level, confidence=confidence,
                provider=provider, model_name=model_name,
                input_fingerprint=fingerprint, result_json=json.dumps(payload, ensure_ascii=False),
                explanation=explanation,
                generated_by_user_id=principal.user_id,
            )
            result.append(self._present(self.repository.add(item)))
            self.audit.log(principal, "generate_ai_suggestion", resource_type="ai_suggestion", resource_id=item.id,
                           details={"ticket_id": ticket.ticket_id, "suggestion_type": suggestion_type,
                                    "provider": provider, "model": model_name, "prompt_version": prompt_version,
                                    "latency_ms": latency_ms, "advisory_only": True})
        return result

    def _llm_context(self, ticket, suggestion_type: str) -> dict:
        """Build context dict for LLM prompt."""
        departments = [d.name for d in self.repository.active_departments()]
        return {
            "ticket_id": ticket.ticket_id,
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
        }

    def list(self, ticket_id: str, principal: Principal):
        self._ticket(ticket_id, principal)
        items = self.repository.list_for_ticket(ticket_id)
        if principal.role == "citizen":
            items = [item for item in items if item.suggestion_type in {"completeness", "summary", "similarity", "risk"}]
        return [self._present(item) for item in items]

    def review(self, suggestion_id: str, decision: str, comment: str | None, principal: Principal):
        item = self.repository.get(suggestion_id)
        if not item:
            raise BusinessError("AI_SUGGESTION_NOT_FOUND", "未找到 AI 建议", 404)
        self._ticket(item.ticket_id, principal)
        item.review_decision = decision
        item.review_comment = comment
        item.reviewed_by_user_id = principal.user_id
        item.reviewed_at = datetime.now(timezone.utc)
        item = self.repository.save(item)
        self.audit.log(principal, "review_ai_suggestion", resource_type="ai_suggestion", resource_id=item.id,
                       details={"decision": decision, "ticket_id": item.ticket_id})
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
        return {
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
        }
