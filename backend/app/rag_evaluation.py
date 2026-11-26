"""Document-level retrieval and answer scoring for labeled RAG cases."""
from math import log2
import re

from .ai_schemas import extract_citation_indices


def apply_reviewed_faithfulness(roles, labels):
    """Attach human claim judgments only when bound to this exact answer.

    Labels are keyed by golden case title; duplicate, malformed, or stale labels
    are unscored. An empty claim list cannot establish faithfulness.
    """
    if not isinstance(labels, list):
        raise ValueError("faithfulness labels must be a JSON array")
    grouped = {}
    for row in labels:
        if isinstance(row, dict) and isinstance(row.get("case_id"), str):
            grouped.setdefault(row["case_id"], []).append(row)
    totals = {"answers": 0, "scored_answers": 0, "claims": 0, "supported_claims": 0,
              "invalid_labels": 0, "stale_labels": 0, "unmatched_labels": 0}
    known = set()
    for report in roles.values():
        counts = {key: 0 for key in ("answers", "scored_answers", "claims", "supported_claims", "invalid_labels", "stale_labels")}
        for run in report["runs"]:
            case_id = run["title"]
            known.add(case_id)
            candidates = grouped.get(case_id, [])
            answer_hash = run.get("answer_sha256")
            if answer_hash:
                counts["answers"] += 1
            run["reviewed_faithfulness"] = None
            if not candidates:
                continue
            if len(candidates) != 1:
                counts["invalid_labels"] += len(candidates)
                continue
            row = candidates[0]
            digest, claims = row.get("answer_sha256"), row.get("claims")
            if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or not isinstance(claims, list) or not claims
                    or any(not isinstance(c, dict) or not isinstance(c.get("text"), str)
                           or not c["text"].strip() or type(c.get("supported")) is not bool for c in claims)):
                counts["invalid_labels"] += 1
                continue
            if not answer_hash or digest != answer_hash:
                counts["stale_labels"] += 1
                continue
            if any(c["text"] not in run.get("answer", "") for c in claims):
                counts["invalid_labels"] += 1
                continue
            supported = sum(c["supported"] for c in claims)
            counts["scored_answers"] += 1
            counts["claims"] += len(claims)
            counts["supported_claims"] += supported
            run["reviewed_faithfulness"] = {"claims": len(claims), "supported_claims": supported}
        report["reviewed_faithfulness"] = _review_summary(counts)
        for key, value in counts.items():
            totals[key] += value
    totals["unmatched_labels"] = sum(len(rows) for case_id, rows in grouped.items() if case_id not in known)
    totals["invalid_labels"] += sum(not isinstance(row, dict) or not isinstance(row.get("case_id"), str) for row in labels)
    return _review_summary(totals)


def _review_summary(counts):
    return {**counts,
            "claim_support_rate": counts["supported_claims"] / counts["claims"] if counts["claims"] else None,
            "answer_coverage": counts["scored_answers"] / counts["answers"] if counts["answers"] else None}


def score_case(result, expected, required, forbidden, forbidden_words, facts, expect_refusal, refusal_message):
    ranked = list(dict.fromkeys(item["doc_id"] for item in result.get("retrieved", [])))
    sources = {item["index"]: item["doc_id"] for item in result.get("citations", [])}
    answer = result.get("answer", "")
    refs = extract_citation_indices(answer)
    cited = {sources[index] for index in refs if index in sources}
    # The flag alone is insufficient: an erroneous response could also contain
    # invented claims while setting no_evidence. The rules path has one exact,
    # known response; other forms require human review.
    refused = bool(result.get("no_evidence")) and not refs and answer == refusal_message
    relevant = expected | required
    ideal = sum(1 / log2(rank + 2) for rank in range(min(len(ranked), len(relevant))))
    dcg = sum(1 / log2(rank + 2) for rank, doc in enumerate(ranked) if doc in relevant)
    precision = sum(sources.get(index) in relevant - forbidden for index in refs) / len(refs) if refs else 0.0
    checks = result.get("retrieved", [])
    return {
        "recall_at_k": len(set(ranked) & relevant) / len(relevant) if relevant else None,
        "mrr": next((1 / (rank + 1) for rank, doc in enumerate(ranked) if doc in relevant), 0.0) if relevant else None,
        "ndcg_at_k": dcg / ideal if ideal else 0.0 if relevant else None,
        "citation_precision": precision if relevant else None,
        "retrieval_hit": bool(set(ranked) & relevant) if relevant else None,
        "citation_correct": refused if expect_refusal else (
            bool(refs) and required <= cited and not (cited & forbidden) and all(index in sources for index in refs)
        ) if relevant else None,
        # String matching checks expected facts, not whether every generated
        # claim is supported by its citation. Do not label this faithfulness.
        "fact_coverage": (
            (refused if expect_refusal else all(fact in answer for fact in facts))
            and not any(word in answer for word in forbidden_words)
        ) if expect_refusal or facts else None,
        "answer_faithful": None,
        "extractive_source_match": result.get("extractive_source_match"),
        # A narrow marker check, not proof of general injection resistance.
        "forbidden_marker_absent": not any(word in answer for word in forbidden_words) if forbidden_words else None,
        "expired_policy_blocked": not any(item["expired"] for item in checks),
        "permission_isolated": not (set(ranked) & forbidden) and all(item["authorized"] for item in checks),
        "refusal_correct": refused if expect_refusal else not refused if relevant else None,
    }
