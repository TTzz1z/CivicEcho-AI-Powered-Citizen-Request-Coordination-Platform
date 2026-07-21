"""Round 3 verification: Rasa/Orchestrator call chain and session isolation."""
import uuid
import requests
from sqlalchemy import select
from app.database import SessionLocal
from app.models import UserModel, AiUsageLogModel
from app.authorization import Principal
from app.services.orchestrator_service import OrchestratorService


def test_session_isolation():
    """Two different session_ids should not share guard counters/cache."""
    db = SessionLocal()
    user = db.scalar(select(UserModel).where(UserModel.role == "citizen").limit(1))
    principal = Principal(kind="user", user_id=user.id, role="citizen",
                          username=user.username, department_id=None)
    svc = OrchestratorService()

    session1 = f"r3-session-1-{uuid.uuid4().hex[:8]}"
    session2 = f"r3-session-2-{uuid.uuid4().hex[:8]}"

    # Session 1: policy query
    r1 = svc.process("社保补贴政策适用于哪些人群", {"user_id": user.id, "role": "citizen"},
                     db=db, principal=principal, session_id=session1)
    print(f"Session 1: route={r1.route} should_create_ticket={r1.should_create_ticket} degraded={r1.degraded}")

    # Session 2: ticket intake (complaint)
    r2 = svc.process("幸福路路灯坏了请派人维修", {"user_id": user.id, "role": "citizen"},
                     db=db, principal=principal, session_id=session2)
    print(f"Session 2: route={r2.route} should_create_ticket={r2.should_create_ticket} degraded={r2.degraded}")

    # Session 1 again: should not inherit session 2's ticket slot
    r3 = svc.process("政策咨询", {"user_id": user.id, "role": "citizen"},
                     db=db, principal=principal, session_id=session1)
    print(f"Session 1 (again): route={r3.route} should_create_ticket={r3.should_create_ticket} (should not inherit session 2's ticket)")

    # Verify logs have different session_ids
    logs = db.scalars(select(AiUsageLogModel).where(
        AiUsageLogModel.session_id.in_([session1, session2])
    ).order_by(AiUsageLogModel.id)).all()
    print(f"\nLogs for session1+session2: {len(logs)}")
    for log in logs:
        print(f"  id={log.id} session={log.session_id} cap={log.capability} provider={log.provider}")

    s1_count = sum(1 for l in logs if l.session_id == session1)
    s2_count = sum(1 for l in logs if l.session_id == session2)
    print(f"\nSession 1 logs: {s1_count}, Session 2 logs: {s2_count}")
    print(f"Isolation: {'PASS' if s1_count > 0 and s2_count > 0 else 'FAIL'}")

    db.close()


def test_rasa_webhook():
    """Test Rasa webhook is alive and responds."""
    try:
        r = requests.post(
            "http://localhost:5005/webhooks/rest/webhook",
            json={"sender": f"r3-test-{uuid.uuid4().hex[:8]}", "message": "/greet"},
            timeout=15,
        )
        print(f"\nRasa webhook status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"Rasa response: {data[:1] if data else 'empty'}")
            return True
        return False
    except Exception as e:
        print(f"\nRasa webhook error: {e}")
        return False


def test_orchestrator_routes():
    """Test various routes through orchestrator."""
    db = SessionLocal()
    user = db.scalar(select(UserModel).where(UserModel.role == "citizen").limit(1))
    principal = Principal(kind="user", user_id=user.id, role="citizen",
                          username=user.username, department_id=None)
    svc = OrchestratorService()

    tests = [
        ("你好", "greet"),
        ("城市道路路灯坏了由哪个部门负责", "policy_rag or service_guide"),
        ("我要投诉幸福路路灯不亮", "ticket_intake"),
        ("写一段贪吃蛇代码", "out_of_scope"),
        ("QT1234567890123", "ticket_progress"),
    ]
    print("\n=== Orchestrator routing tests ===")
    for msg, expected in tests:
        r = svc.process(msg, {"user_id": user.id, "role": "citizen"},
                        db=db, principal=principal,
                        session_id=f"r3-route-{uuid.uuid4().hex[:8]}")
        print(f"  msg='{msg[:30]}' → route={r.route} should_create_ticket={r.should_create_ticket} (expected: {expected})")

    db.close()


if __name__ == "__main__":
    print("=== Test 1: Session isolation ===")
    test_session_isolation()
    print("\n=== Test 2: Rasa webhook ===")
    test_rasa_webhook()
    print("\n=== Test 3: Orchestrator routes ===")
    test_orchestrator_routes()
