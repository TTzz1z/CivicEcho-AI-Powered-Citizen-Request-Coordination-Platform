"""Round 3 verification: service_guide success cases + no-evidence rejection."""
import uuid
from sqlalchemy import select
from app.database import SessionLocal
from app.models import UserModel
from app.authorization import Principal
from app.services.kb_service import KnowledgeBaseService


def main():
    db = SessionLocal()
    user = db.scalar(select(UserModel).where(UserModel.role == "citizen").limit(1))
    principal = Principal(kind="user", user_id=user.id, role="citizen",
                          username=user.username, department_id=None)

    tests = [
        ("service_guide", "怎么办身份证"),
        ("policy_rag", "社保补贴政策适用于哪些人群"),
        ("service_guide", "如何提取住房公积金"),
        ("policy_rag", "最低生活保障申请条件是什么"),
        ("service_guide", "量子力学是什么"),  # no-evidence case
    ]
    for route, q in tests:
        svc = KnowledgeBaseService(db)
        r = svc.rag_answer(q, principal, route="citizen_query",
                           session_id=f"r3-{uuid.uuid4().hex[:8]}",
                           request_id=f"r3-{uuid.uuid4().hex[:8]}")
        cites = r.get("citations", [])
        print(f"=== {route}: {q} ===")
        print(f"  no_evidence={r.get('no_evidence')} citations={len(cites)}")
        if cites:
            c = cites[0]
            print(f"  citation[0]: title={c.get('title')}")
            print(f"    doc_number={c.get('doc_number')}")
            print(f"    issuing_authority={c.get('issuing_authority')}")
            print(f"    version={c.get('version')}")
            print(f"    published_at={c.get('published_at')}")
            print(f"    expires_at={c.get('expires_at')}")
            print(f"    detail_url={c.get('detail_url')}")
            print(f"    excerpt[:60]={c.get('excerpt', '')[:60]}")
        ans = r.get("answer", "")
        print(f"  answer[:120]={ans[:120]}")
        print()
    db.close()


if __name__ == "__main__":
    main()
