"""Unified Government Service Orchestrator.

Routes citizen messages through a layered pipeline:

  1. 固定规则和模板（greet / help / emergency / ticket_id / handoff）
  2. Rasa 或轻量意图分类（领域边界判定 in_domain）
  3. 业务接口、FAQ 或 RAG 检索（政策→RAG；工单→DB；部门→配置）
  4. 必要时才调用大模型（且受 Guard 限流/预算/缓存约束）

字段：in_domain / route / confidence / requires_llm / model_tier /
      rejection_reason / estimated_cost_level

简单问候、感谢、帮助说明直接走模板，不调用大模型。
写代码、写论文、娱乐闲聊、角色扮演、内容创作等无关问题使用固定中文兜底回复，
不进入大模型生成。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..authorization import Principal
from ..config import get_settings
from ..llm_client import LlmResult, get_llm_client
from ..logging_config import request_id_context
from .ai_usage_recorder import (
    AiUsageRecorder,
    UsageContext,
    make_context,
    CAP_ORCHESTRATOR_CLASSIFY,
    CAP_POLICY_RAG,
    CAP_SERVICE_GUIDE,
    CAP_TICKET_DRAFT,
)
from .language_guard import ensure_chinese_response
from .orchestrator_guard import (
    GuardDecision,
    OrchestratorGuard,
    UsageRecord,
    get_guard,
)

logger = logging.getLogger(__name__)

# --- Route constants ---
ROUTES = (
    "policy_rag", "service_guide", "ticket_intake", "suggestion_intake",
    "ticket_progress", "department_navigation", "emergency_route",
    "general_chat", "human_handoff", "clarify", "out_of_scope",
)

# --- Model tier ---
MODEL_TIER_RULES = "rules"
MODEL_TIER_EMBEDDING = "embedding"
MODEL_TIER_LLM_LITE = "llm_lite"
MODEL_TIER_LLM_FULL = "llm_full"

# --- Cost level ---
COST_LEVEL_NONE = "none"        # no model cost
COST_LEVEL_LOW = "low"          # rules / embedding
COST_LEVEL_MEDIUM = "medium"    # llm_lite (classification / extraction)
COST_LEVEL_HIGH = "high"        # llm_full (policy / service guide answer)

# --- Rule-based detection patterns ---
TICKET_ID_RE = re.compile(r"QT\d{12,16}", re.IGNORECASE)
EMERGENCY_WORDS = (
    "火灾", "爆炸", "坍塌", "有人受伤", "生命危险", "触电", "溺水", "中毒", "自杀", "持刀", "行凶",
    # 走失/失踪类：引导立即报警，不当成功能说明或普通工单
    "走失", "失踪", "下落不明", "没回家", "未回家", "找不到人", "孩子不见", "小孩不见", "老人走失",
)
POLICY_WORDS = ("政策", "补贴", "福利", "待遇", "社保", "公积金", "入学", "落户", "人才", "博士", "硕士", "低保", "医保", "养老", "残疾", "优抚", "退伍", "军人")
SERVICE_GUIDE_WORDS = ("怎么办", "如何办理", "需要什么材料", "去哪里办", "办理流程", "办理条件", "需要什么证件", "怎么申请", "如何申请", "在哪办", "手续")
SUGGESTION_WORDS = ("建议", "希望增加", "应该", "能不能", "是否可以增加", "改善", "优化")
PROGRESS_WORDS = ("进度", "处理到哪", "办到哪了", "什么时候", "查询工单", "工单状态")
DEPT_NAV_WORDS = ("找哪个部门", "哪个部门管", "归谁管", "不知道找谁", "该找谁", "哪个窗口")
HANDOFF_WORDS = ("转人工", "人工服务", "找人工", "要真人", "投诉你们", "态度差")
GREET_WORDS = ("你好", "您好", "在吗", "谢谢", "感谢", "再见", "拜拜", "早上好", "下午好", "晚上好")
# 仅「能力说明」问法；禁止裸「帮助/求助」命中真实诉求长句
HELP_EXACT = ("help", "帮助", "功能", "怎么用", "帮助一下")
HELP_CAPABILITY_WORDS = (
    "怎么用", "能做什么", "能干啥", "能干什么", "你会什么", "你可以做什么",
    "有什么功能", "有哪些功能", "你能干嘛", "你会干啥", "可以做什么", "做什么用",
    "你是做什么的", "介绍一下你的功能",
)

# User explicitly confirms creating a consultation ticket (after policy_rag no-evidence).
# Only such explicit confirmation may trigger ticket_intake for a consultation.
CREATE_CONSULTATION_TICKET_WORDS = (
    "创建咨询工单", "创建一个咨询工单", "建咨询工单", "提交咨询工单", "转咨询工单", "我要创建咨询工单",
)

# Demand/reflect markers used to detect multi-intent scenarios
# (consultation + demand). Keep distinct from complaint_words so that
# "政策不合理" / "窗口不给办" don't by themselves create a ticket.
REFLECT_WORDS = (
    "反映", "不合理", "不规范", "不给办", "一直不给办", "窗口不给", "拒绝办理",
    "推诿", "踢皮球", "投诉窗口", "投诉办事",
)

# Out-of-domain markers (high-confidence rejection)
OUT_OF_DOMAIN_KEYWORDS = (
    "写代码", "写一段代码", "编程", "python", "javascript", "java 代码",
    "贪吃蛇", "游戏代码", "算法", "leetcode",
    "写论文", "论文润色", "学术",
    "写诗", "写小说", "续写", "故事", "角色扮演", "扮演",
    "讲笑话", "娱乐", "闲聊",
    "翻译", "翻译一下",
)

# 固定中文兜底回复（超出范围）
OUT_OF_DOMAIN_MESSAGE = (
    "我主要提供政策咨询、办事指南、投诉建议、公共事务求助和工单进度查询。"
    "您可以告诉我想了解的政策、需要办理的事项，或者需要反映的问题。"
)

# 固定中文问候
GREET_MESSAGE = (
    "您好！我是倾听助手，可以帮您咨询政策、提交投诉建议、查询工单进度。"
    "请问有什么可以帮您？"
)

# 固定中文帮助
HELP_MESSAGE = (
    "我可以帮您：\n"
    "- 提交投诉、建议、咨询或求助事项\n"
    "- 查询工单办理进度\n"
    "- 咨询政策或办事指南\n"
    "- 转接人工服务\n\n"
    "请直接用一句话描述您的需求。"
)

# 访客超额提示
VISITOR_LIMIT_MESSAGE = (
    "访客模式下您今日的咨询次数已达上限。"
    "请登录市民账号后继续咨询政策或提交工单。"
)

# 模型不可用降级提示
LLM_UNAVAILABLE_MESSAGE = (
    "智能解答服务暂时不可用，已为您切换到检索模式。"
    "您可以查看下方检索到的政策原文，或拨打 12345 咨询。"
)

# Dynamic ticket fields by business category
DYNAMIC_FIELDS = {
    "教育投诉": [
        {"key": "school_name", "label": "学校名称", "type": "input", "required": True},
        {"key": "grade_class", "label": "年级/班级", "type": "input", "required": False},
        {"key": "involved_person", "label": "涉事人员", "type": "input", "required": False},
        {"key": "occurred_at_text", "label": "发生时间", "type": "input", "required": True},
        {"key": "risk_note", "label": "是否存在受伤或持续风险", "type": "select", "options": ["是", "否", "不确定"], "required": True},
    ],
    "路灯报修": [
        {"key": "road_or_community", "label": "道路/小区", "type": "input", "required": True},
        {"key": "fault_location", "label": "故障位置", "type": "input", "required": True},
        {"key": "fault_count", "label": "故障数量", "type": "input", "required": False},
        {"key": "duration", "label": "持续时间", "type": "input", "required": True},
        {"key": "photo", "label": "现场照片", "type": "upload", "required": False},
    ],
    "default": [
        {"key": "location", "label": "发生地点", "type": "input", "required": True},
        {"key": "occurred_at_text", "label": "发生时间", "type": "input", "required": False},
        {"key": "target", "label": "涉及对象", "type": "input", "required": False},
    ],
}


@dataclass
class OrchestratorResult:
    primary_intent: str
    route: str
    confidence: float
    in_domain: bool = True
    requires_llm: bool = False
    model_tier: str = MODEL_TIER_RULES
    estimated_cost_level: str = COST_LEVEL_NONE
    rejection_reason: str = ""
    urgency: str = "normal"
    sensitive_flags: list[str] = field(default_factory=list)
    routing_reason: str = ""
    should_create_ticket: bool = False
    should_clarify: bool = False
    clarify_question: Optional[str] = None
    # Payload varies by route
    message: str = ""
    payload: dict = field(default_factory=dict)
    # Audit fields
    cache_hit: bool = False
    degraded: bool = False
    degrade_reason: str = ""
    rate_limited: bool = False
    budget_exceeded: bool = False


class OrchestratorService:
    """Stateful orchestrator with guard + audit."""

    def __init__(self):
        self.settings = get_settings()
        self.llm = get_llm_client()
        self.guard = get_guard()

    # ----------------------------------------------------------------
    # Public entry
    # ----------------------------------------------------------------

    def process(self, message: str, user_context: dict, route_hint: Optional[str] = None,
                db: Optional[Session] = None, principal: Optional[Principal] = None,
                session_id: Optional[str] = None) -> OrchestratorResult:
        """Main entry: process a citizen message and return routing decision + response."""
        return self._enforce_language(self._process_inner(
            message, user_context, route_hint, db=db, principal=principal,
            session_id=session_id,
        ))

    def _enforce_language(self, result: OrchestratorResult) -> OrchestratorResult:
        """Strip any English residue before the result leaves the service."""
        result.message = ensure_chinese_response(result.message, source="orchestrator_service")
        if result.clarify_question:
            result.clarify_question = ensure_chinese_response(
                result.clarify_question, source="orchestrator_clarify",
            )
        return result

    def _process_inner(self, message: str, user_context: dict, route_hint: Optional[str] = None,
                       db: Optional[Session] = None, principal: Optional[Principal] = None,
                       session_id: Optional[str] = None) -> OrchestratorResult:
        """Inner pipeline without language post-filter."""
        text = (message or "").strip()
        request_id = request_id_context.get() or uuid.uuid4().hex
        user_key = self._user_key(user_context)
        # Round 2 r2-5: per-session isolation. Callers should pass a fresh
        # session_id per conversation. If absent, generate a one-shot id so
        # turn counters / guard buckets are NOT shared across conversations
        # via the legacy "user:default" fallback. New sessions never inherit
        # previous ticket slots because OrchestratorService is stateless.
        if not session_id:
            session_id = f"{user_key}:s-{uuid.uuid4().hex[:12]}"

        # Empty
        if not text:
            return OrchestratorResult(
                primary_intent="empty", route="general_chat", confidence=1.0,
                message="请输入您的问题。", in_domain=True, requires_llm=False,
                model_tier=MODEL_TIER_RULES, estimated_cost_level=COST_LEVEL_NONE,
            )

        # Step 1: Rule-based detection (highest priority, no LLM cost)
        rule_result = self._rule_detect(text, user_context)
        if rule_result and rule_result.confidence >= 0.9:
            self.guard.increment_session_turn(session_id)
            # For policy_rag / service_guide (reproducible answers), consult
            # semantic cache first to skip redundant RAG/LLM work on repeats.
            # ticket_intake / suggestion_intake are NOT cached: each complaint is unique.
            cacheable_routes = ("policy_rag", "service_guide")
            if rule_result.route in cacheable_routes and rule_result.requires_llm \
                    and rule_result.model_tier == MODEL_TIER_LLM_FULL:
                cached = self.guard._cache_lookup_semantic(
                    text, route_hint,
                    principal=principal, session_id=session_id,
                    request_id=request_id, route=rule_result.route,
                )
                if cached is not None:
                    cached_result = self._materialize_cached(cached, text, user_context)
                    self._record_usage(db, request_id, user_context, cached_result,
                                     latency_ms=0, cache_hit=True, success=True,
                                     principal=principal, session_id=session_id)
                    return cached_result
            executed = self._execute_route(rule_result, text, user_context, db=db,
                                           principal=principal, request_id=request_id,
                                           user_key=user_key, session_id=session_id)
            # Store reproducible LLM-bound rule-routed results in semantic cache
            if executed.route in cacheable_routes and executed.requires_llm \
                    and executed.model_tier == MODEL_TIER_LLM_FULL \
                    and not executed.degraded and not executed.cache_hit:
                self.guard.cache_store(
                    text=text, route=executed.route, route_hint=route_hint,
                    payload={"message": executed.message, "payload": executed.payload},
                    principal=principal, session_id=session_id,
                    request_id=request_id,
                )
            return executed

        # Step 2: Out-of-domain rejection (rule-based, before any LLM call)
        ood_result = self._out_of_domain_detect(text)
        if ood_result:
            self.guard.increment_session_turn(session_id)
            self._record_usage(db, request_id, user_context, ood_result,
                              latency_ms=0, success=True,
                              principal=principal, session_id=session_id)
            return ood_result

        # Step 3: LLM semantic classification (only if rules didn't fire and not OOD)
        # Run pre-flight guard for LLM-bound classification
        guard_decision = self.guard.pre_check(
            text=text, user_key=user_key, route_hint=route_hint,
            session_id=session_id, requires_llm=True,
        )
        if not guard_decision.allowed:
            self.guard.increment_session_turn(session_id)
            return self._handle_rejection(guard_decision, request_id, db, user_context,
                                          principal=principal, session_id=session_id)

        # Cache hit: return cached
        if guard_decision.cache_hit and guard_decision.cached_result:
            self.guard.increment_session_turn(session_id)
            cached = guard_decision.cached_result
            result = self._materialize_cached(cached, text, user_context)
            self._record_usage(db, request_id, user_context, result,
                             latency_ms=0, cache_hit=True, success=True,
                             principal=principal, session_id=session_id)
            return result

        # LLM classify (records its own usage via AiUsageRecorder inside)
        llm_result, llm_latency, llm_call_result = self._llm_classify_with_guard(
            text, user_context, route_hint, guard_decision, user_key,
            db=db, principal=principal, session_id=session_id, request_id=request_id,
        )
        if llm_result and llm_result.confidence >= 0.6 and llm_result.in_domain:
            self.guard.increment_session_turn(session_id)
            executed = self._execute_route(llm_result, text, user_context, db=db,
                                          principal=principal, request_id=request_id,
                                          user_key=user_key, session_id=session_id)
            # Store reproducible LLM answers in semantic cache (exclude ticket_intake)
            if executed.route in ("policy_rag", "service_guide") \
                    and executed.requires_llm and executed.model_tier == MODEL_TIER_LLM_FULL \
                    and not executed.degraded and not executed.cache_hit:
                self.guard.cache_store(
                    text=text, route=executed.route, route_hint=route_hint,
                    payload={"message": executed.message, "payload": executed.payload},
                    principal=principal, session_id=session_id,
                    request_id=request_id,
                )
            return executed

        # LLM said out-of-domain explicitly (LLM call already recorded)
        if llm_result and not llm_result.in_domain:
            self.guard.increment_session_turn(session_id)
            ood = OrchestratorResult(
                primary_intent="out_of_scope", route="out_of_scope", confidence=llm_result.confidence,
                in_domain=False, requires_llm=False, model_tier=MODEL_TIER_LLM_LITE,
                estimated_cost_level=COST_LEVEL_MEDIUM, rejection_reason="llm_out_of_domain",
                message=OUT_OF_DOMAIN_MESSAGE, routing_reason=llm_result.routing_reason,
            )
            return ood

        # Low confidence: single clarify, do NOT loop (LLM call already recorded)
        if llm_result and llm_result.confidence >= 0.4:
            self.guard.increment_session_turn(session_id)
            clarify_result = OrchestratorResult(
                primary_intent=llm_result.primary_intent, route="clarify",
                confidence=llm_result.confidence, should_clarify=True,
                clarify_question="请问您是想咨询政策、提交投诉/建议，还是查询工单进度？",
                message="我不太确定您的具体需求，请帮我确认一下。",
                requires_llm=False, model_tier=MODEL_TIER_LLM_LITE,
                estimated_cost_level=COST_LEVEL_MEDIUM,
            )
            return clarify_result

        # Fallback: out-of-domain (do NOT call LLM again; LLM call already recorded)
        self.guard.increment_session_turn(session_id)
        fallback = OrchestratorResult(
            primary_intent="unknown", route="out_of_scope", confidence=0.3,
            in_domain=False, requires_llm=False, model_tier=MODEL_TIER_RULES,
            estimated_cost_level=COST_LEVEL_NONE, rejection_reason="low_confidence_fallback",
            message=OUT_OF_DOMAIN_MESSAGE,
        )
        return fallback

    # ----------------------------------------------------------------
    # Rule-based detection (Step 1) — no LLM cost
    # ----------------------------------------------------------------

    def _rule_detect(self, text: str, user_context: dict) -> Optional[OrchestratorResult]:
        """Rule-based detection with high confidence. No LLM cost."""
        # Emergency
        emergency_hits = [w for w in EMERGENCY_WORDS if w in text]
        if emergency_hits:
            return OrchestratorResult(
                primary_intent="emergency", route="emergency_route", confidence=0.95,
                urgency="urgent", sensitive_flags=emergency_hits,
                routing_reason=f"命中紧急关键词：{'、'.join(emergency_hits)}",
                requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE,
            )

        # Ticket progress query (e.g. "查询QT2026...")
        ticket_match = TICKET_ID_RE.search(text)
        if ticket_match or any(w in text for w in PROGRESS_WORDS):
            return OrchestratorResult(
                primary_intent="ticket_progress", route="ticket_progress", confidence=0.95,
                routing_reason="包含工单编号或进度查询关键词",
                payload={"ticket_id": ticket_match.group(0).upper() if ticket_match else None},
                requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE,
            )

        # Human handoff
        if any(w in text for w in HANDOFF_WORDS):
            return OrchestratorResult(
                primary_intent="human_handoff", route="human_handoff", confidence=0.95,
                routing_reason="用户明确要求人工服务",
                requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE,
            )

        # Greetings (template, no LLM)
        if text.lower() in GREET_WORDS or (len(text) <= 8 and any(w in text for w in GREET_WORDS)):
            return OrchestratorResult(
                primary_intent="greet", route="general_chat", confidence=0.95,
                message=GREET_MESSAGE,
                requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE,
                routing_reason="问候关键词命中",
            )

        # Help / 能做什么 — 仅能力问询，避免「寻求帮助」等真实诉求误入
        if self._is_capability_help_query(text):
            return OrchestratorResult(
                primary_intent="help", route="general_chat", confidence=0.95,
                message=HELP_MESSAGE,
                requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE,
                routing_reason="帮助说明关键词命中",
            )

        # Department navigation
        if any(w in text for w in DEPT_NAV_WORDS):
            return OrchestratorResult(
                primary_intent="department_navigation", route="department_navigation", confidence=0.9,
                routing_reason="用户询问部门归属",
                requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE,
            )

        # Multi-intent detection (Round 2 r2-4): when a message clearly mixes
        # consultation (policy / service guide) with a demand (complaint / reflect),
        # never silently pick one route — return a structured clarification.
        policy_hit = any(w in text for w in POLICY_WORDS)
        service_guide_hit = any(w in text for w in SERVICE_GUIDE_WORDS)
        # Complaint/demand markers (do NOT include "怎么办" / "问题" / "反映" alone)
        complaint_words = ("投诉", "举报", "坏了", "故障", "不亮", "破损", "漏水",
                           "噪音", "扰民", "体罚", "打人", "坑洼", "垃圾", "臭", "堵")
        complaint_hit = any(w in text for w in complaint_words)
        reflect_hit = any(w in text for w in REFLECT_WORDS)
        consult_hit = policy_hit or service_guide_hit
        demand_hit = complaint_hit or reflect_hit
        if consult_hit and demand_hit:
            consult_label = "政策咨询" if policy_hit else "办事指南"
            clarify_msg = (
                f"我注意到您的问题既涉及{consult_label}，又涉及诉求反映。请选择您希望优先处理的方式：\n"
                "1. 先查看政策/办事指南\n"
                "2. 同时创建诉求工单\n"
                "3. 仅提交投诉/反映\n"
                "请回复数字（1/2/3）或简单说明您的选择（一轮澄清，仍不明确将转人工）。"
            )
            return OrchestratorResult(
                primary_intent="multi_intent_clarify", route="clarify", confidence=0.92,
                should_clarify=True,
                clarify_question=clarify_msg,
                message=clarify_msg,
                requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE,
                routing_reason=f"多意图检测：{consult_label}+诉求反映",
                payload={"multi_intent": True, "consult_type": consult_label,
                         "has_complaint": complaint_hit, "has_reflect": reflect_hit},
            )

        # Suggestion
        if any(w in text for w in SUGGESTION_WORDS) and not any(w in text for w in ("投诉", "举报", "坏了", "故障")):
            return OrchestratorResult(
                primary_intent="suggestion", route="suggestion_intake", confidence=0.9,
                routing_reason="命中建议类关键词", should_create_ticket=True,
                requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE,
            )

        # User explicitly confirms creating a consultation ticket (after policy_rag
        # no-evidence prompt). Only this explicit confirmation may create a ticket
        # for a consultation — policy_rag itself never auto-creates tickets.
        if any(w in text for w in CREATE_CONSULTATION_TICKET_WORDS):
            return OrchestratorResult(
                primary_intent="consultation_ticket", route="ticket_intake", confidence=0.95,
                routing_reason="用户明确确认创建咨询工单", should_create_ticket=True,
                requires_llm=True, model_tier=MODEL_TIER_LLM_LITE,
                estimated_cost_level=COST_LEVEL_MEDIUM,
                payload={"draft_request_type": "咨询"},
            )

        # Service guide
        if any(w in text for w in SERVICE_GUIDE_WORDS):
            return OrchestratorResult(
                primary_intent="service_guide", route="service_guide", confidence=0.9,
                routing_reason="命中办事指南关键词",
                requires_llm=True, model_tier=MODEL_TIER_LLM_FULL,
                estimated_cost_level=COST_LEVEL_HIGH,
            )

        # Policy
        policy_hits = [w for w in POLICY_WORDS if w in text]
        if len(policy_hits) >= 1 and not any(w in text for w in ("投诉", "举报", "坏了", "故障", "不亮", "破损")):
            return OrchestratorResult(
                primary_intent="policy_consultation", route="policy_rag", confidence=0.9,
                routing_reason=f"命中政策关键词：{'、'.join(policy_hits)}",
                requires_llm=True, model_tier=MODEL_TIER_LLM_FULL,
                estimated_cost_level=COST_LEVEL_HIGH,
            )

        # Complaint / repair / help → ticket_intake
        complaint_words = ("投诉", "举报", "坏了", "故障", "不亮", "破损", "漏水", "噪音", "扰民", "体罚", "打人", "坑洼", "垃圾", "臭", "堵")
        if any(w in text for w in complaint_words):
            return OrchestratorResult(
                primary_intent="complaint", route="ticket_intake", confidence=0.9,
                routing_reason="命中投诉/报修关键词", should_create_ticket=True,
                requires_llm=True, model_tier=MODEL_TIER_LLM_LITE,
                estimated_cost_level=COST_LEVEL_MEDIUM,
            )

        return None

    # ----------------------------------------------------------------
    # Out-of-domain detection (Step 2) — no LLM cost
    # ----------------------------------------------------------------

    def _out_of_domain_detect(self, text: str) -> Optional[OrchestratorResult]:
        """Detect clearly out-of-domain requests via keyword rules."""
        text_lower = text.lower()
        for kw in OUT_OF_DOMAIN_KEYWORDS:
            if kw in text_lower or kw in text:
                return OrchestratorResult(
                    primary_intent="out_of_scope", route="out_of_scope", confidence=0.92,
                    in_domain=False, requires_llm=False, model_tier=MODEL_TIER_RULES,
                    estimated_cost_level=COST_LEVEL_NONE,
                    rejection_reason=f"keyword_oob:{kw}",
                    routing_reason=f"命中超范围关键词：{kw}",
                    message=OUT_OF_DOMAIN_MESSAGE,
                )
        return None

    # ----------------------------------------------------------------
    # LLM classification (Step 3) — only when necessary
    # ----------------------------------------------------------------

    def _llm_classify_with_guard(self, text: str, user_context: dict,
                                 route_hint: Optional[str],
                                 guard_decision: GuardDecision,
                                 user_key: str, *,
                                 db: Optional[Session] = None,
                                 principal: Optional[Principal] = None,
                                 session_id: str = "",
                                 request_id: str = "") -> tuple[Optional[OrchestratorResult], int, Optional[LlmResult]]:
        """LLM classification with guard / budget / degradation.

        Records the LLM call via AiUsageRecorder with real token usage parsed
        from the model response. Returns (intent_result, latency_ms, llm_result).
        """
        # If guard mandates degradation, record a degraded rules-tier entry
        if guard_decision.degraded:
            self._record_degraded_classification(db, request_id, user_context, principal,
                                                  session_id, guard_decision.degrade_reason)
            return None, 0, None

        if not self.llm.available:
            self._record_degraded_classification(db, request_id, user_context, principal,
                                                  session_id, "llm_unavailable")
            return None, 0, None

        # Acquire concurrency slot
        if not self.guard.acquire_llm_slot(user_key):
            self._record_degraded_classification(db, request_id, user_context, principal,
                                                  session_id, "concurrent_exceeded")
            return None, 0, None

        try:
            started = time.perf_counter()
            intent_result, llm_result = self._llm_classify(text, user_context, route_hint)
            latency_ms = int((time.perf_counter() - started) * 1000)
            # Override latency with measured value for accurate recording
            if llm_result is not None:
                llm_result.latency_ms = latency_ms
            # Record real usage (success or failure) via AiUsageRecorder
            if llm_result is not None and db is not None:
                ctx = make_context(
                    capability=CAP_ORCHESTRATOR_CLASSIFY,
                    route=intent_result.route if intent_result else "general_chat",
                    principal=principal,
                    session_id=session_id,
                    request_id=request_id,
                )
                recorder = AiUsageRecorder(db)
                recorder.record_llm_call(
                    ctx, llm_result,
                    degraded=not llm_result.success,
                    degrade_reason="llm_failed" if not llm_result.success else None,
                )
            return intent_result, latency_ms, llm_result
        finally:
            self.guard.release_llm_slot(user_key)

    def _record_degraded_classification(self, db, request_id, user_context, principal,
                                         session_id, degrade_reason) -> None:
        """Record a degraded orchestrator_classify entry (no LLM call made)."""
        if db is None:
            return
        try:
            ctx = make_context(
                capability=CAP_ORCHESTRATOR_CLASSIFY,
                route="general_chat",
                principal=principal,
                session_id=session_id,
                request_id=request_id,
            )
            recorder = AiUsageRecorder(db)
            # Build a synthetic LlmResult representing the degradation
            synthetic = LlmResult(
                success=False, data=None, model="rules",
                error=degrade_reason, error_code=degrade_reason,
            )
            recorder.record_llm_call(
                ctx, synthetic,
                degraded=True, degrade_reason=degrade_reason,
            )
        except Exception as exc:
            logger.warning("record_degraded_classification failed: %s", exc)

    def _llm_classify(self, text: str, user_context: dict, route_hint: Optional[str] = None) -> tuple[Optional[OrchestratorResult], LlmResult]:
        """Use LLM for semantic intent classification + in_domain judgment.

        Returns (intent_result, llm_result). llm_result is always non-None so
        callers can record accurate token usage even on parse failure.
        """
        if not self.llm.available:
            return None, LlmResult(success=False, data=None, model="rules",
                                    error="no_api_key", error_code="no_api_key")

        prompt = f"""你是政务服务意图分类器。根据用户消息判断意图类别和是否属于政务服务范围。

政务服务范围：政策咨询、办事指南、投诉举报、意见建议、公共事务求助、工单查询、部门导航、紧急事项分流、简单问候和帮助说明。
不属于范围：写代码、写论文、娱乐闲聊、角色扮演、内容创作、翻译、其他无关问题。

可选类别：
- policy_rag: 政策咨询（补贴、福利、社保、入学条件等）
- service_guide: 办事指南（怎么办、去哪办、需要什么材料）
- ticket_intake: 投诉/举报/求助/报修（需要部门实际处理的问题）
- suggestion_intake: 意见与建议
- ticket_progress: 查询工单进度
- department_navigation: 不知道找哪个部门
- emergency_route: 紧急/危险情况
- general_chat: 问候、感谢、帮助说明
- human_handoff: 要求人工服务
- out_of_scope: 与政务服务无关的问题

用户消息：{text}
{f'路由提示：{route_hint}' if route_hint else ''}

输出严格JSON：{{"primary_intent":"...","route":"...","confidence":0.0-1.0,"in_domain":true/false,"urgency":"normal|elevated|urgent","should_create_ticket":true/false,"reasoning":"简短理由"}}"""

        llm_result = self.llm.complete_raw(
            system="你是政务服务意图分类器，只输出JSON。",
            user=prompt,
            temperature=0.1,
            max_tokens=300,
            json_mode=True,
            capability=CAP_ORCHESTRATOR_CLASSIFY,
        )
        if not llm_result.success or not llm_result.content:
            return None, llm_result

        try:
            content = llm_result.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(content)
        except (json.JSONDecodeError, IndexError) as exc:
            logger.warning("LLM classify JSON parse failed: %s", exc)
            return None, llm_result

        route = data.get("route", "general_chat")
        if route not in ROUTES:
            route = "general_chat"
        in_domain = bool(data.get("in_domain", True))
        # If LLM says out_of_scope, force in_domain=False
        if route == "out_of_scope":
            in_domain = False
        requires_llm = route in ("policy_rag", "service_guide", "ticket_intake")
        model_tier = MODEL_TIER_LLM_FULL if route in ("policy_rag", "service_guide") else (
            MODEL_TIER_LLM_LITE if route == "ticket_intake" else MODEL_TIER_LLM_LITE
        )
        cost_level = COST_LEVEL_HIGH if model_tier == MODEL_TIER_LLM_FULL else COST_LEVEL_MEDIUM
        intent = OrchestratorResult(
            primary_intent=data.get("primary_intent", "unknown"),
            route=route,
            confidence=float(data.get("confidence", 0.5)),
            in_domain=in_domain,
            urgency=data.get("urgency", "normal"),
            should_create_ticket=bool(data.get("should_create_ticket", False)),
            routing_reason=data.get("reasoning", "LLM分类"),
            requires_llm=requires_llm,
            model_tier=model_tier,
            estimated_cost_level=cost_level,
            rejection_reason="" if in_domain else "llm_out_of_domain",
        )
        return intent, llm_result

    # ----------------------------------------------------------------
    # Route execution
    # ----------------------------------------------------------------

    def _execute_route(self, result: OrchestratorResult, text: str, user_context: dict,
                       db: Optional[Session] = None, principal: Optional[Principal] = None,
                       request_id: str = "", user_key: str = "",
                       session_id: str = "") -> OrchestratorResult:
        """Execute the routed handler and populate response payload.

        LLM-bound routes (policy_rag, service_guide, ticket_intake) record
        their own usage via AiUsageRecorder inside their respective handlers.
        Rules-tier routes are recorded here via _record_usage.
        """
        route = result.route

        if route == "emergency_route":
            flags = result.sensitive_flags or []
            missing_person = any(
                w in flags or w in text
                for w in ("走失", "失踪", "下落不明", "没回家", "未回家", "找不到人", "孩子不见", "小孩不见", "老人走失")
            )
            if missing_person:
                result.message = (
                    "您描述的情况可能涉及人员走失或失联，请优先保障安全并立即求助：\n"
                    "1. 请立即拨打 110 报警，说明走失时间、地点和特征\n"
                    "2. 可同步联系学校、监护人或附近派出所\n"
                    "3. 非紧急政务咨询可拨打 12345\n\n"
                    "本平台不能替代报警。在报警后，如需形成书面记录由相关部门跟进，我可以帮您起草工单草稿。是否需要？"
                )
            else:
                result.message = (
                    "检测到您的描述可能涉及紧急情况。请注意：\n"
                    "1. 如有人身危险，请立即拨打 110 或 120\n"
                    "2. 如涉及火灾，请拨打 119\n"
                    "3. 如涉及燃气泄漏，请远离现场并拨打燃气公司电话\n\n"
                    "在确保安全后，我可以帮您生成工单草稿由相关部门跟进。是否需要？"
                )
            result.payload = {"emergency_type": "、".join(flags), "can_create_ticket": True}

        elif route == "ticket_progress":
            # Direct DB query — no LLM
            result.message = self._ticket_progress_response(result, db, principal)
            result.payload = {"ticket_id": result.payload.get("ticket_id")}
            result.requires_llm = False
            result.model_tier = MODEL_TIER_RULES
            result.estimated_cost_level = COST_LEVEL_NONE

        elif route == "policy_rag":
            # MUST go through RAG first, never let LLM answer without retrieval.
            # KB service records embedding_query + policy_rag LLM calls itself.
            result = self._policy_response_with_rag(result, text, db, principal, request_id,
                                                    user_context, user_key, session_id)

        elif route == "service_guide":
            # MUST go through RAG. KB service records embedding_query + service_guide LLM calls.
            result = self._service_guide_response_with_guard(result, text, user_context,
                                                            user_key, db, principal,
                                                            request_id, session_id)

        elif route == "ticket_intake":
            result.should_create_ticket = True
            result.message = "我已识别到您的诉求信息，请在工单草稿面板中核对并补充。"
            category = self._detect_category(text)
            # Draft extraction records its own usage via AiUsageRecorder
            draft = self._extract_ticket_draft_with_guard(text, user_context, user_key,
                                                          db, principal, request_id, session_id)
            # Honor explicit user-confirmed request_type (e.g. consultation ticket
            # after policy_rag no-evidence prompt) over rule-based default.
            forced_request_type = result.payload.get("draft_request_type") if result.payload else None
            if forced_request_type:
                draft["request_type"] = forced_request_type
            result.payload = {
                "draft": draft,
                "dynamic_fields": DYNAMIC_FIELDS.get(category, DYNAMIC_FIELDS["default"]),
                "category": category,
            }

        elif route == "suggestion_intake":
            result.should_create_ticket = True
            result.message = "感谢您的建议！我已整理为建议工单草稿，请确认后提交。"
            result.payload = {
                "draft": {
                    "request_type": "建议",
                    "description": text,
                    "location": "",
                    "target": "",
                    "contact": user_context.get("contact", ""),
                },
                "dynamic_fields": [
                    {"key": "location", "label": "涉及区域/部门", "type": "input", "required": False},
                ],
                "category": "建议",
            }
            result.requires_llm = False
            result.model_tier = MODEL_TIER_RULES
            result.estimated_cost_level = COST_LEVEL_NONE

        elif route == "department_navigation":
            result.message = self._dept_nav_response(text, db)
            result.payload = {"query": text}
            result.requires_llm = False
            result.model_tier = MODEL_TIER_RULES
            result.estimated_cost_level = COST_LEVEL_NONE

        elif route == "human_handoff":
            result.message = (
                "我理解您希望获得人工服务。当前可通过以下方式联系：\n"
                "1. 拨打 12345 政务服务热线\n"
                "2. 前往所在社区服务中心\n"
                "3. 在工作时间联系坐席人员\n\n"
                "如果您愿意，也可以继续描述问题，我会尽力协助。"
            )

        elif route == "general_chat":
            if not result.message:
                result.message = GREET_MESSAGE

        elif route == "out_of_scope":
            if not result.message:
                result.message = OUT_OF_DOMAIN_MESSAGE

        # Record rules-tier usage only (LLM-bound routes record themselves).
        # This keeps a row in ai_usage_logs for every orchestrator decision,
        # so admin dashboards can show route distribution even for free paths.
        if result.model_tier == MODEL_TIER_RULES and request_id:
            self._record_usage(db, request_id, user_context, result,
                             latency_ms=0, success=True,
                             principal=principal, session_id=session_id)

        return result

    # ----------------------------------------------------------------
    # Policy RAG — must retrieve first, only call LLM if retrieval has evidence
    # ----------------------------------------------------------------

    def _policy_response_with_rag(self, result: OrchestratorResult, query: str,
                                  db: Optional[Session], principal: Optional[Principal],
                                  request_id: str, user_context: dict, user_key: str,
                                  session_id: str = "") -> OrchestratorResult:
        """Policy consultation MUST go through RAG. LLM only summarizes retrieved evidence.

        The KB service records embedding_query + policy_rag LLM calls via
        AiUsageRecorder. policy_rag NEVER sets should_create_ticket=True.
        """
        # P0-E fix: policy_rag must never create a ticket automatically
        result.should_create_ticket = False
        if db is None or principal is None:
            # No DB context — degrade to LLM-free fallback
            result.message = (
                f"关于“{query}”的政策信息，建议您：\n"
                "1. 拨打 12345 政务服务热线咨询\n"
                "2. 前往所在社区或街道服务中心\n"
                "3. 登录本地政务服务网查询\n\n"
                "如果您认为政策执行存在问题，我可以帮您转为投诉工单。"
            )
            result.degraded = True
            result.degrade_reason = "no_db_context"
            result.requires_llm = False
            result.model_tier = MODEL_TIER_RULES
            result.estimated_cost_level = COST_LEVEL_NONE
            return result

        try:
            from .kb_service import KnowledgeBaseService
            svc = KnowledgeBaseService(db)
            # Pass session_id/request_id through so KB service can record usage
            rag_result = svc.rag_answer(query, principal, route="citizen_query",
                                         session_id=session_id, request_id=request_id)
            result.payload = {
                "query": query,
                "citations": rag_result.get("citations", []),
                "retrieval_count": rag_result.get("retrieval_count", 0),
                "no_evidence": rag_result.get("no_evidence", False),
                "source": "kb_rag",
            }
            result.message = rag_result.get("answer", "")
            # RAG already used LLM internally for the answer; mark tier
            result.model_tier = MODEL_TIER_LLM_FULL
            result.estimated_cost_level = COST_LEVEL_HIGH
            result.requires_llm = True
            if rag_result.get("no_evidence"):
                # No evidence: don't fabricate. Provide channels.
                result.degraded = False
                result.payload["no_evidence"] = True
            return result
        except Exception as exc:
            logger.warning("Policy RAG failed, degrading: %s", exc)
            result.message = LLM_UNAVAILABLE_MESSAGE + f"\n\n关于“{query}”，建议拨打 12345 咨询或前往政务服务大厅。"
            result.degraded = True
            result.degrade_reason = "rag_failed"
            result.requires_llm = False
            result.model_tier = MODEL_TIER_RULES
            result.estimated_cost_level = COST_LEVEL_NONE
            return result

    # ----------------------------------------------------------------
    # Service guide — RAG-based (P0-E fix: must retrieve, never free-form LLM)
    # ----------------------------------------------------------------

    def _service_guide_response_with_guard(self, result: OrchestratorResult, query: str,
                                          user_context: dict, user_key: str,
                                          db: Optional[Session] = None,
                                          principal: Optional[Principal] = None,
                                          request_id: str = "",
                                          session_id: str = "") -> OrchestratorResult:
        """Service guide response via RAG with guard/concurrency.

        P0-E: service_guide MUST retrieve published PUBLIC guide documents
        from the KB; LLM only summarizes retrieved evidence. No free-form
        LLM generation without citations.
        """
        # P0-E: service_guide never auto-creates a ticket
        result.should_create_ticket = False
        # Default payload marks no_evidence; success path overwrites with real citations.
        result.payload = {"no_evidence": True}
        if db is None or principal is None:
            result.message = (
                f"关于“{query}”的办事指南，建议您拨打 12345 或前往政务服务大厅咨询具体办理流程和所需材料。"
            )
            result.degraded = True
            result.degrade_reason = "no_db_context"
            result.requires_llm = False
            result.model_tier = MODEL_TIER_RULES
            result.estimated_cost_level = COST_LEVEL_NONE
            return result

        if not self.llm.available:
            result.message = (
                f"关于“{query}”的办事指南，建议您拨打 12345 或前往政务服务大厅咨询具体办理流程和所需材料。"
            )
            result.degraded = True
            result.degrade_reason = "llm_unavailable"
            result.requires_llm = False
            result.model_tier = MODEL_TIER_RULES
            result.estimated_cost_level = COST_LEVEL_NONE
            return result
        if not self.guard.acquire_llm_slot(user_key):
            result.message = (
                f"关于“{query}”的办事指南，建议您拨打 12345 或前往政务服务大厅咨询具体办理流程和所需材料。"
            )
            result.degraded = True
            result.degrade_reason = "concurrent_exceeded"
            result.requires_llm = False
            result.model_tier = MODEL_TIER_RULES
            result.estimated_cost_level = COST_LEVEL_NONE
            return result
        try:
            from .kb_service import KnowledgeBaseService
            svc = KnowledgeBaseService(db)
            # Reuse the RAG pipeline with a service_guide-specific route so
            # admin dashboards can break down service_guide vs policy_rag usage.
            guide_result = svc.rag_answer(
                query, principal, route="service_guide",
                session_id=session_id, request_id=request_id,
            )
            result.payload = {
                "query": query,
                "citations": guide_result.get("citations", []),
                "retrieval_count": guide_result.get("retrieval_count", 0),
                "no_evidence": guide_result.get("no_evidence", False),
                "source": "kb_rag",
            }
            result.message = guide_result.get("answer", "")
            result.model_tier = MODEL_TIER_LLM_FULL
            result.estimated_cost_level = COST_LEVEL_HIGH
            result.requires_llm = True
            if guide_result.get("no_evidence"):
                # No evidence found; never let LLM fabricate materials/timeframes.
                result.payload["no_evidence"] = True
            return result
        except Exception as exc:
            logger.warning("Service guide RAG failed: %s", exc)
            result.message = (
                f"关于“{query}”的办事指南，建议您拨打 12345 或前往政务服务大厅咨询具体办理流程和所需材料。"
            )
            result.degraded = True
            result.degrade_reason = "rag_failed"
            result.requires_llm = False
            result.model_tier = MODEL_TIER_RULES
            result.estimated_cost_level = COST_LEVEL_NONE
            return result
        finally:
            self.guard.release_llm_slot(user_key)

    # ----------------------------------------------------------------
    # Ticket draft extraction — guarded LLM (records own usage)
    # ----------------------------------------------------------------

    def _extract_ticket_draft_with_guard(self, text: str, user_context: dict,
                                         user_key: str,
                                         db: Optional[Session] = None,
                                         principal: Optional[Principal] = None,
                                         request_id: str = "",
                                         session_id: str = "") -> dict:
        """Extract ticket draft fields. Uses rules first, LLM only if available & slot free.

        Records the LLM call via AiUsageRecorder with real token usage.
        """
        draft = {
            "request_type": "投诉",
            "description": text,
            "location": "",
            "occurred_at_text": "",
            "target": "",
            "contact": user_context.get("contact", ""),
        }
        # Detect request type by rules
        if any(w in text for w in ("建议", "希望", "增加")):
            draft["request_type"] = "建议"
        elif any(w in text for w in ("求助", "帮忙", "困难")):
            draft["request_type"] = "求助"
        elif any(w in text for w in ("咨询", "请问", "怎么")):
            draft["request_type"] = "咨询"

        # Optional LLM extraction — degrade gracefully
        if not self.llm.available:
            self._record_degraded_draft(db, request_id, principal, session_id, "llm_unavailable")
            return draft
        if not self.guard.acquire_llm_slot(user_key):
            self._record_degraded_draft(db, request_id, principal, session_id, "concurrent_exceeded")
            return draft
        try:
            prompt = f"""从以下市民诉求中提取结构化信息。
输出JSON：{{"request_type":"投诉|建议|咨询|求助","location":"地点或空","occurred_at_text":"时间或空","target":"涉及对象或空","impact":"影响描述"}}

市民描述：{text}"""
            llm_result = self.llm.complete_raw(
                system="你是信息提取器，只输出JSON。",
                user=prompt,
                temperature=0.1,
                max_tokens=300,
                json_mode=True,
                capability=CAP_TICKET_DRAFT,
            )
            # Record real usage
            if db is not None:
                ctx = make_context(
                    capability=CAP_TICKET_DRAFT,
                    route="ticket_intake",
                    principal=principal,
                    session_id=session_id,
                    request_id=request_id,
                )
                recorder = AiUsageRecorder(db)
                recorder.record_llm_call(
                    ctx, llm_result,
                    degraded=not llm_result.success,
                    degrade_reason="llm_failed" if not llm_result.success else None,
                )
            if llm_result.success and llm_result.content:
                content = llm_result.content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                data = json.loads(content)
                draft["request_type"] = data.get("request_type", draft["request_type"])
                draft["location"] = data.get("location", "") or ""
                draft["occurred_at_text"] = data.get("occurred_at_text", "") or ""
                draft["target"] = data.get("target", "") or ""
        except Exception as exc:
            logger.warning("Draft extraction LLM failed: %s", exc)
        finally:
            self.guard.release_llm_slot(user_key)
        return draft

    def _record_degraded_draft(self, db, request_id, principal, session_id, degrade_reason) -> None:
        """Record a degraded ticket_draft entry (no LLM call made)."""
        if db is None:
            return
        try:
            ctx = make_context(
                capability=CAP_TICKET_DRAFT,
                route="ticket_intake",
                principal=principal,
                session_id=session_id,
                request_id=request_id,
            )
            recorder = AiUsageRecorder(db)
            synthetic = LlmResult(success=False, data=None, model="rules",
                                   error=degrade_reason, error_code=degrade_reason)
            recorder.record_llm_call(ctx, synthetic, degraded=True, degrade_reason=degrade_reason)
        except Exception as exc:
            logger.warning("record_degraded_draft failed: %s", exc)

    # ----------------------------------------------------------------
    # Ticket progress — direct DB query, no LLM
    # ----------------------------------------------------------------

    def _ticket_progress_response(self, result: OrchestratorResult, db: Optional[Session],
                                  principal: Optional[Principal]) -> str:
        """Query ticket status directly from DB. No LLM. Always works."""
        ticket_id = result.payload.get("ticket_id")
        if not ticket_id:
            return "请问您要查询的工单编号是？（格式：QT + 数字，例如 QT202607130000000001）"
        if db is None:
            return f"已收到工单 {ticket_id} 的查询请求，但当前无法连接工单服务，请稍后重试或前往「我的工单」页面查看。"
        try:
            from ..models import TicketModel
            from sqlalchemy import select
            ticket = db.scalar(select(TicketModel).where(TicketModel.ticket_id == ticket_id))
            if not ticket:
                return f"未找到工单 {ticket_id}。请确认工单编号是否正确，或登录提交该工单的市民账号后查询。"
            # Permission check: citizen can only see own tickets
            if principal and principal.role == "citizen" and ticket.creator_user_id != principal.user_id:
                return f"工单 {ticket_id} 不属于当前登录账号。如需查询他人工单，请通过 12345 联系相关部门。"
            status_map = {
                "pending": "等待受理", "accepted": "已受理", "in_progress": "正在办理",
                "resolved": "已办结待确认", "closed": "已办结", "rejected": "已驳回",
            }
            status_label = status_map.get(ticket.status, ticket.status)
            return (
                f"工单 {ticket_id} 当前状态：{status_label}。\n"
                f"诉求类型：{ticket.request_type}\n"
                f"提交时间：{ticket.created_at.strftime('%Y-%m-%d %H:%M') if ticket.created_at else '未知'}\n"
                f"如需了解更详细的办理过程，请前往「我的工单」页面查看。"
            )
        except Exception as exc:
            logger.warning("Ticket progress query failed: %s", exc)
            return f"查询工单 {ticket_id} 时出现问题，请稍后重试。"

    # ----------------------------------------------------------------
    # Department navigation — read real config from DB
    # ----------------------------------------------------------------

    def _dept_nav_response(self, query: str, db: Optional[Session]) -> str:
        """Department navigation. Reads real department list from DB."""
        if db is None:
            return (
                "根据您描述的问题，建议您：\n"
                "1. 拨打 12345 政务服务热线，由综合坐席为您转接对应部门\n"
                "2. 前往所在社区服务中心，工作人员可协助判断归属\n\n"
                "如果您能更具体描述问题类型（如市政、教育、环保等），我可以给出更精准的部门建议。"
            )
        try:
            from ..models import DepartmentModel
            from sqlalchemy import select
            depts = list(db.scalars(select(DepartmentModel).where(DepartmentModel.is_active == True).limit(8)).all())  # noqa: E712
            if not depts:
                return (
                    "当前未查询到部门信息。建议拨打 12345 政务服务热线，由综合坐席为您转接对应部门。"
                )
            dept_list = "\n".join(f"- {d.name}：{d.description or '负责相应政务事项'}" for d in depts)
            return (
                "根据您描述的问题，建议您参考以下部门信息：\n"
                f"{dept_list}\n\n"
                "如需进一步确认归属，请拨打 12345 政务服务热线，"
                "或前往所在社区服务中心由工作人员协助判断。"
            )
        except Exception as exc:
            logger.warning("Dept nav query failed: %s", exc)
            return (
                "查询部门信息时出现问题。建议拨打 12345 政务服务热线咨询。"
            )

    def _detect_category(self, text: str) -> str:
        """Detect business category for dynamic fields."""
        if any(w in text for w in ("学校", "老师", "体罚", "教育", "学生", "幼儿园")):
            return "教育投诉"
        if any(w in text for w in ("路灯", "照明", "灯", "不亮")):
            return "路灯报修"
        return "default"

    # ----------------------------------------------------------------
    # Rejection / degradation handlers
    # ----------------------------------------------------------------

    def _handle_rejection(self, decision: GuardDecision, request_id: str,
                          db: Optional[Session], user_context: dict,
                          principal: Optional[Principal] = None,
                          session_id: str = "") -> OrchestratorResult:
        """Convert a GuardDecision rejection into an OrchestratorResult."""
        reason = decision.rejection_reason
        if reason == "input_too_long":
            result = OrchestratorResult(
                primary_intent="rejected", route="out_of_scope", confidence=1.0,
                in_domain=False, requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE, rejection_reason=reason,
                message=f"您输入的内容过长（上限 {self.guard.input_max_chars} 字），请精简后重新描述您的需求。",
            )
        elif reason == "session_exceeded":
            result = OrchestratorResult(
                primary_intent="rejected", route="out_of_scope", confidence=1.0,
                in_domain=False, requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE, rejection_reason=reason,
                message="本次会话已较长，建议您新建会话或前往「我的工单」页面继续操作。",
            )
        elif reason in ("rate_limited", "concurrent_exceeded"):
            result = OrchestratorResult(
                primary_intent="rejected", route="out_of_scope", confidence=1.0,
                in_domain=True, requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE, rejection_reason=reason,
                rate_limited=(reason == "rate_limited"),
                degraded=(reason == "concurrent_exceeded"),
                degrade_reason=reason,
                message="您的请求过于频繁，请稍后再试，或直接拨打 12345 反映。",
            )
        elif reason in ("budget_exceeded", "platform_budget_exceeded"):
            # Visitor or logged-in budget exceeded
            role = user_context.get("role", "anonymous")
            if role == "anonymous":
                msg = VISITOR_LIMIT_MESSAGE
            else:
                msg = "您今日的智能咨询次数已达上限，相关业务仍可通过工单或 12345 办理。"
            result = OrchestratorResult(
                primary_intent="rejected", route="out_of_scope", confidence=1.0,
                in_domain=True, requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE, rejection_reason=reason,
                budget_exceeded=True, degraded=True, degrade_reason=reason,
                message=msg,
            )
        else:
            result = OrchestratorResult(
                primary_intent="rejected", route="out_of_scope", confidence=1.0,
                in_domain=False, requires_llm=False, model_tier=MODEL_TIER_RULES,
                estimated_cost_level=COST_LEVEL_NONE, rejection_reason=reason,
                message=OUT_OF_DOMAIN_MESSAGE,
            )
        # Record rejection as a rules-tier event with degraded flag when applicable
        self._record_usage(db, request_id, user_context, result,
                         latency_ms=0, success=False,
                         rate_limited=result.rate_limited,
                         degraded=result.degraded,
                         principal=principal, session_id=session_id)
        return result

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _materialize_cached(self, cached: dict, text: str, user_context: dict) -> OrchestratorResult:
        """Convert a cached payload into an OrchestratorResult."""
        payload = cached.get("payload", {})
        return OrchestratorResult(
            primary_intent="cached", route=cached.get("route", "general_chat"),
            confidence=1.0, in_domain=True,
            requires_llm=False, model_tier=MODEL_TIER_RULES,
            estimated_cost_level=COST_LEVEL_NONE,
            routing_reason="cache_hit",
            message=payload.get("message", ""),
            payload=payload.get("payload", {}),
            cache_hit=True,
        )

    def _is_capability_help_query(self, text: str) -> bool:
        """True only for short capability questions, not real 求助/投诉 sentences."""
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        if normalized in HELP_EXACT:
            return True
        # Real incident descriptions are longer; keep capability probes short
        if len(normalized) > 16:
            return False
        return any(w in normalized for w in HELP_CAPABILITY_WORDS)

    def _user_key(self, user_context: dict) -> str:
        """Build user_key for rate limit / budget tracking."""
        uid = user_context.get("user_id")
        if uid:
            return f"user:{uid}"
        # Anonymous: use IP if available, else a session marker
        ip = user_context.get("ip") or user_context.get("remote_addr") or "anon"
        return f"ip:{ip}"

    def _record_usage(self, db: Optional[Session], request_id: str,
                      user_context: dict, result: OrchestratorResult,
                      latency_ms: int = 0, success: bool = True,
                      input_tokens: int = 0, output_tokens: int = 0,
                      cache_hit: bool = False, rate_limited: bool = False,
                      degraded: bool = False,
                      principal: Optional[Principal] = None,
                      session_id: str = "") -> None:
        """Record rules-tier / rejection usage via AiUsageRecorder.

        LLM-bound routes record their own usage with real tokens inside their
        handlers. This method only writes rules-tier rows (zero tokens by
        design — no LLM was actually called for these paths).
        """
        if db is None:
            return
        try:
            capability = _capability_for_route(result.route)
            ctx = make_context(
                capability=capability,
                route=result.route,
                principal=principal,
                session_id=session_id,
                request_id=request_id,
            )
            recorder = AiUsageRecorder(db)
            recorder.record_rules_call(
                ctx,
                model_name=result.model_tier or "rules",
                latency_ms=latency_ms,
                cache_hit=cache_hit or result.cache_hit,
                degrade_reason=result.degrade_reason if (degraded or result.degraded) else None,
            )
        except Exception as exc:
            logger.warning("record_usage wrapper failed: %s", exc)


def _capability_for_route(route: str) -> str:
    """Map an orchestrator route to an AI capability label for rules-tier rows."""
    mapping = {
        "policy_rag": CAP_POLICY_RAG,
        "service_guide": CAP_SERVICE_GUIDE,
        "ticket_intake": CAP_TICKET_DRAFT,
        "suggestion_intake": CAP_TICKET_DRAFT,
    }
    return mapping.get(route, CAP_ORCHESTRATOR_CLASSIFY)


_orchestrator: Optional[OrchestratorService] = None


def get_orchestrator() -> OrchestratorService:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrchestratorService()
    return _orchestrator


def reset_orchestrator_for_tests() -> None:
    """Reset orchestrator singleton. For tests only."""
    global _orchestrator
    from .orchestrator_guard import reset_guard_for_tests
    reset_guard_for_tests()
    _orchestrator = OrchestratorService()
