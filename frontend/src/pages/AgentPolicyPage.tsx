import { KbRagPanel } from '../components/KbRagPanel'

/** 坐席端政策辅助页：基于公开政策库的 RAG 问答（结构化回答 + 元数据筛选 + 引用溯源）。 */
export function AgentPolicyPage() {
  return (
    <KbRagPanel
      eyebrow="AGENT POLICY ASSIST"
      title="政策辅助检索"
      description="查询已发布的政策与办事指南，查看回答引用的原文及有效日期，可按地区、领域、人群过滤检索范围。"
      enableFilters
    />
  )
}
