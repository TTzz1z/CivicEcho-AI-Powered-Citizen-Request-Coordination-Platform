import { KbRagPanel } from '../components/KbRagPanel'

/** 市民端政策咨询页：基于公开政策库的 RAG 问答（9 段式结构化回答）。 */
export function CitizenPolicyPage() {
  return (
    <KbRagPanel
      eyebrow="CITIZEN POLICY RAG"
      title="政策咨询"
      description="查询已发布的政策和办事指南，查看回答引用的原文及有效日期。"
      enableFilters={false}
    />
  )
}
