"""Round 3 verification: trigger real LLM calls and capture ai_usage_logs evidence."""
import uuid
from sqlalchemy import select
from app.database import SessionLocal
from app.models import KbChunkModel, UserModel, AiUsageLogModel
from app.authorization import Principal
from app.services.kb_service import KnowledgeBaseService


def main():
    db = SessionLocal()
    user = db.scalar(select(UserModel).where(UserModel.role == "citizen").limit(1))
    print(f"Using citizen: id={user.id} username={user.username}")
    principal = Principal(kind="user", user_id=user.id, role="citizen",
                          username=user.username, department_id=None)

    # Check chunks embedding status
    chunks = db.scalars(select(KbChunkModel).limit(5)).all()
    print("--- chunks embedding status ---")
    for c in chunks:
        emb_none = c.embedding is None
        print(f"  chunk id={c.id} doc_id={c.document_id} emb_none={emb_none} model={c.embedding_model} provider={c.embedding_provider}")

    # Baseline log count
    before = db.scalar(select(AiUsageLogModel.id).order_by(AiUsageLogModel.id.desc()).limit(1))
    print(f"--- baseline max log id: {before} ---")

    queries = [
        ("policy_rag", "城市道路路灯坏了由哪个部门负责维修"),
        ("service_guide", "路灯故障报修需要什么材料如何办理"),
        ("policy_rag", "社保补贴政策适用于哪些人群"),
        ("service_guide", "怎么办身份证"),
    ]

    for route_label, query in queries:
        session_id = f"r3-{uuid.uuid4().hex[:8]}"
        request_id = f"r3-req-{uuid.uuid4().hex[:8]}"
        print(f"\n=== {route_label}: {query} ===")
        try:
            svc = KnowledgeBaseService(db)
            result = svc.rag_answer(query, principal, route="citizen_query",
                                    session_id=session_id, request_id=request_id)
            answer = result.get("answer", "")
            citations = result.get("citations", [])
            print(f"  answer_len={len(answer)} citations={len(citations)} no_evidence={result.get('no_evidence')} retrieval_count={result.get('retrieval_count')}")
            if citations:
                c = citations[0]
                print(f"  first citation: title={c.get('title')} doc_number={c.get('doc_number')} excerpt={c.get('excerpt','')[:60]}")
            print(f"  answer preview: {answer[:120]}")
        except Exception as exc:
            print(f"  ERROR: {exc}")

    # Check new logs
    db.expire_all()
    new_logs = db.scalars(select(AiUsageLogModel).where(AiUsageLogModel.id > (before or 0)).order_by(AiUsageLogModel.id)).all()
    print(f"\n=== {len(new_logs)} new ai_usage_logs entries ===")
    for log in new_logs:
        print(f"  id={log.id} cap={log.capability} provider={log.provider} model={log.model_name} in_tok={log.input_tokens} out_tok={log.output_tokens} total={log.total_tokens} latency={log.latency_ms} cost={log.estimated_cost_rmb} degraded={log.degraded} reason={log.degrade_reason} success={log.success} usage_unavail={log.usage_unavailable}")

    # Find at least one real LLM log
    real_llm = db.scalar(select(AiUsageLogModel).where(
        AiUsageLogModel.provider != "rules",
        AiUsageLogModel.total_tokens > 0,
    ).order_by(AiUsageLogModel.id.desc()).limit(1))
    print(f"\n=== real LLM log (provider!=rules, total_tokens>0) ===")
    if real_llm:
        print(f"  FOUND: id={real_llm.id} cap={real_llm.capability} provider={real_llm.provider} model={real_llm.model_name} total_tokens={real_llm.total_tokens} cost={real_llm.estimated_cost_rmb} usage_unavailable={real_llm.usage_unavailable}")
    else:
        print("  NOT FOUND - LLM was never called or returned no usage")

    db.close()


if __name__ == "__main__":
    main()
