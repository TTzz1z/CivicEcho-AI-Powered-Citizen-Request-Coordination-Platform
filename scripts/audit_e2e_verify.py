"""End-to-end acceptance verification for 倾听助手 orchestrator.
Tests 10 acceptance scenarios with real DB + real routing + real audit log.
"""
import json
import urllib.request

BASE = "http://localhost:8001"
PASSWORD = "tingting-seed-demo-2026"


def login(username):
    body = json.dumps({"username": username, "password": PASSWORD}).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/api/v1/auth/login", data=body,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())["data"]["access_token"]


def chat(token, message):
    body = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/api/v1/orchestrator/chat", data=body,
                                  headers={"Content-Type": "application/json; charset=utf-8",
                                           "Authorization": f"Bearer {token}"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["data"]


def main():
    token = login("citizen_local")
    cases = [
        ("你好", "general_chat", "rules"),
        ("帮助", "general_chat", "rules"),
        ("帮我写贪吃蛇代码", "out_of_scope", "rules"),
        ("博士家属有什么待遇", "policy_rag", "llm_full"),
        ("路灯坏了三天", "ticket_intake", None),
        ("查询QT2026071300000001", "ticket_progress", "rules"),
        ("我要投诉小区物业", "ticket_intake", None),
        ("谢谢", "general_chat", "rules"),
        ("写一篇论文", "out_of_scope", "rules"),
        ("怎么办理身份证", "service_guide", None),
    ]
    print(f"{'#':<3} {'Input':<28} {'ExpectedRoute':<22} {'ActualRoute':<22} {'Tier':<10} {'LLM':<5} {'Cost':<8} {'OK'}")
    print("-" * 130)
    pass_count = 0
    for i, (msg, exp_route, exp_tier) in enumerate(cases, 1):
        try:
            r = chat(token, msg)
            actual_route = r["route"]
            tier = r["model_tier"]
            requires_llm = r["requires_llm"]
            cost = r["estimated_cost_level"]
            ok = actual_route == exp_route
            if ok:
                pass_count += 1
            print(f"{i:<3} {msg[:26]:<28} {exp_route:<22} {actual_route:<22} {tier:<10} {'Y' if requires_llm else 'N':<5} {cost:<8} {'OK' if ok else 'FAIL'}")
        except Exception as e:
            print(f"{i:<3} {msg[:26]:<28} {exp_route:<22} ERROR: {e}")
    print(f"\nPassed: {pass_count}/{len(cases)}")

    # Test semantic cache: send same policy question twice
    print("\n--- Cache Test ---")
    r1 = chat(token, "博士家属有什么待遇")
    print(f"First: route={r1['route']} cache_hit={r1['cache_hit']}")
    r2 = chat(token, "博士家属有什么待遇")
    print(f"Second: route={r2['route']} cache_hit={r2['cache_hit']}")

    # Test admin AI usage stats
    print("\n--- Admin AI Usage Stats ---")
    admin_token = login("admin_local")
    req = urllib.request.Request(f"{BASE}/api/v1/admin/ai-usage/stats?days=7",
                                  headers={"Authorization": f"Bearer {admin_token}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        stats = json.loads(r.read())["data"]
    print(f"Total calls: {stats.get('total_calls')}")
    print(f"Total tokens: {stats.get('total_input_tokens', 0) + stats.get('total_output_tokens', 0)}")
    print(f"Cache hit rate: {stats.get('cache_hit_rate', 0):.2%}")
    print(f"By route: {len(stats.get('by_route', []))} routes")
    print(f"By tier: {len(stats.get('by_tier', []))} tiers")


if __name__ == "__main__":
    main()
