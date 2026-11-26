from app.rag_evaluation import apply_reviewed_faithfulness, score_case


def score(result, *, expected={1}, required={1}, forbidden={2}, words=(), facts=("48小时",), refusal=False):
    return score_case(result, expected, required, forbidden, words, facts, refusal, "没有证据")


def test_ranking_and_citations_do_not_imply_faithfulness():
    result = {"retrieved": [{"doc_id": 3, "expired": False, "authorized": True},
                            {"doc_id": 1, "expired": False, "authorized": True}],
              "citations": [{"index": 1, "doc_id": 1}, {"index": 2, "doc_id": 3}],
              "answer": "48小时 [来源1]，另有未经支持的说法 [来源2]"}
    metrics = score(result)
    assert metrics["recall_at_k"] == 1
    assert metrics["mrr"] == 0.5
    assert metrics["citation_precision"] == 0.5
    assert metrics["fact_coverage"] is True
    assert metrics["answer_faithful"] is None
    assert metrics["extractive_source_match"] is None


def test_refusal_requires_actual_rules_response():
    kwargs = dict(expected=set(), required=set(), facts=(), refusal=True)
    assert score({"no_evidence": True, "answer": "没有证据"}, **kwargs)["refusal_correct"] is True
    assert score({"no_evidence": True, "answer": "没有证据，但我猜是48小时"}, **kwargs)["refusal_correct"] is False


def test_marker_and_permission_failures_are_independent():
    result = {"answer": "注入成功 [来源1]", "retrieved": [{"doc_id": 2, "expired": True, "authorized": False}],
              "citations": [{"index": 1, "doc_id": 2}]}
    metrics = score(result, words=("注入成功",))
    assert metrics["forbidden_marker_absent"] is False
    assert metrics["permission_isolated"] is False
    assert metrics["expired_policy_blocked"] is False
    assert metrics["citation_correct"] is False


def test_review_labels_are_bound_to_exact_answer_and_invalid_are_unscored():
    digest = "a" * 64
    roles = {"citizen": {"runs": [
        {"title": "correct", "answer_sha256": digest, "answer": "a b"},
        {"title": "stale", "answer_sha256": "b" * 64},
        {"title": "malformed", "answer_sha256": digest},
        {"title": "unreviewed", "answer_sha256": digest},
    ]}}
    labels = [
        {"case_id": "correct", "answer_sha256": digest,
         "claims": [{"text": "a", "supported": True}, {"text": "b", "supported": False}]},
        {"case_id": "stale", "answer_sha256": digest, "claims": [{"text": "a", "supported": True}]},
        {"case_id": "malformed", "answer_sha256": digest, "claims": [{"text": "a", "supported": "yes"}]},
    ]
    summary = apply_reviewed_faithfulness(roles, labels)
    assert summary["claim_support_rate"] == 0.5
    assert summary["answer_coverage"] == 0.25
    assert summary["stale_labels"] == summary["invalid_labels"] == 1
    assert roles["citizen"]["runs"][1]["reviewed_faithfulness"] is None
