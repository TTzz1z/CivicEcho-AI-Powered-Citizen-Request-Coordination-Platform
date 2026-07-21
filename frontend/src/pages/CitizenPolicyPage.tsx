import { KbRagPanel } from '../components/KbRagPanel'

/** 市民端政策咨询页：基于公开政策库的 RAG 问答（9 段式结构化回答）。 */
export function CitizenPolicyPage() {
  return (
    <KbRagPanel
      eyebrow="CITIZEN POLICY RAG"
      title="政策咨询"
      description="基于公开政策库、办事指南与常见问题为您提供权威解答。每个结论均附政策来源，未检索到依据时不会编造。"
      enableFilters={false}
    />
  )
}
