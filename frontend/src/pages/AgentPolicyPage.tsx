import { KbRagPanel } from '../components/KbRagPanel'

/** 坐席端政策辅助页：基于公开政策库的 RAG 问答（7 段式结构化回答 + 元数据筛选）。 */
export function AgentPolicyPage() {
  return (
    <KbRagPanel
      eyebrow="AGENT POLICY ASSIST"
      title="政策辅助检索"
      description="为坐席回复市民咨询提供政策依据要点、办理流程、所需材料与负责部门。可按地区、领域、人群过滤检索范围。"
      enableFilters
    />
  )
}
