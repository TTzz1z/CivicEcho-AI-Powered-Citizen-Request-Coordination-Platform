"""Replay the repository's labeled demonstration corpus."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy import select  # noqa: E402

from app.authorization import Principal  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.embedding_client import EMBEDDING_VERSION, get_embedding_client  # noqa: E402
from app.llm_client import RESPONSE_SCHEMA_VERSION, get_llm_client  # noqa: E402
from app.models import KbDocumentModel, KbEvalCaseModel  # noqa: E402
from app.rag_evaluation import apply_reviewed_faithfulness  # noqa: E402
from app.services.kb_service import KnowledgeBaseService, RAG_PROMPT_VERSION, RETRIEVAL_VERSION  # noqa: E402

STRATIFIED_15_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "retrieval_and_multidoc",
        ("eval_lighting_query", "transport-1", "property-1", "identity-1", "education-1", "welfare-1", "social-1", "lighting-1"),
    ),
    (
        "expired_policy",
        ("eval_expired_policy_blocked", "fund-1"),
    ),
    (
        "no_evidence",
        ("no-evidence-1", "no-evidence-5"),
    ),
    (
        "permission_isolation",
        ("permission-1-citizen", "permission-1-department_staff", "permission-positive-1"),
    ),
    (
        "prompt_injection",
        ("injection-1", "injection-5", "injection-9"),
    ),
)

_STRATIFIED_QUOTAS: dict[str, int] = {
    "retrieval_and_multidoc": 6,
    "expired_policy": 1,
    "no_evidence": 2,
    "permission_isolation": 3,
    "prompt_injection": 3,
}


def _extract_case_key(case: KbEvalCaseModel) -> str:
    note = case.notes or ""
    if note.startswith("[golden:"):
        return note.split("]", 1)[0][len("[golden:") :]
    if note.startswith("[seed:"):
        return note.split("]", 1)[0][len("[seed:") :]
    return str(case.title or case.id)


def select_stratified_case_ids(
    cases: list[KbEvalCaseModel],
    *,
    n: int = 15,
    corpus: str = "all",
) -> list[str]:
    """Deterministically select a stratified representative subset of eval case keys."""
    if n <= 0:
        return []
    eligible = [
        c for c in cases
        if getattr(c, "is_active", True)
        and (corpus != "golden" or (getattr(c, "notes", None) or "").startswith("[golden:"))
    ]
    by_key = {_extract_case_key(c): c for c in eligible}
    selected: list[str] = []
    seen: set[str] = set()

    bucket_queues: list[list[str]] = []
    for bucket_name, preferred in STRATIFIED_15_BUCKETS:
        quota = _STRATIFIED_QUOTAS[bucket_name]
        queue: list[str] = []
        for key in preferred:
            if len(queue) >= quota:
                break
            if key in by_key and key not in seen:
                queue.append(key)
        if queue:
            bucket_queues.append(queue)

    while len(selected) < min(n, len(eligible)) and bucket_queues:
        progressed = False
        for queue in bucket_queues:
            if queue:
                nxt = queue.pop(0)
                if nxt not in seen:
                    selected.append(nxt)
                    seen.add(nxt)
                    progressed = True
                    if len(selected) >= n:
                        break
        if not progressed:
            break

    if len(selected) < min(n, len(eligible)):
        scenario_groups: dict[str, list[str]] = {}
        for key in sorted(by_key):
            if key in seen:
                continue
            scen = getattr(by_key[key], "scenario", "other") or "other"
            scenario_groups.setdefault(scen, []).append(key)
        ordered_scenarios = sorted(scenario_groups)
        while len(selected) < min(n, len(eligible)) and ordered_scenarios:
            progressed = False
            for scen in ordered_scenarios:
                bucket = scenario_groups[scen]
                if bucket:
                    nxt = bucket.pop(0)
                    if nxt not in seen:
                        selected.append(nxt)
                        seen.add(nxt)
                        progressed = True
                        if len(selected) >= n:
                            break
            if not progressed:
                break

    return selected[:n]


def _aggregate_overall(roles_report: dict[str, dict]) -> dict:
    all_runs: list[dict] = []
    for role_report in roles_report.values():
        all_runs.extend(role_report.get("runs", []))
    total = len(all_runs)
    if total == 0:
        return {"total": 0, "metrics": {}}
    metrics: dict = {}
    for key in (
        "retrieval_hit", "citation_correct", "answer_faithful", "fact_coverage",
        "extractive_source_match", "forbidden_marker_absent", "expired_policy_blocked",
        "permission_isolated", "refusal_correct", "recall_at_k", "mrr", "ndcg_at_k",
        "citation_precision", "no_evidence", "latency_ms",
    ):
        values = [row[key] for row in all_runs if row.get(key) is not None]
        label = {"no_evidence": "no_answer_rate", "latency_ms": "avg_latency_ms"}.get(key, key)
        if key in (
            "retrieval_hit", "citation_correct", "answer_faithful", "fact_coverage",
            "extractive_source_match", "forbidden_marker_absent",
            "expired_policy_blocked", "permission_isolated", "refusal_correct",
        ):
            label += "_rate"
        metrics[label] = round(sum(values) / len(values), 3) if values else None
    metrics["failed_cases"] = sum(bool(row.get("error")) for row in all_runs)
    metrics["extractive_source_match_scored"] = sum(
        row.get("extractive_source_match") is not None for row in all_runs
    )
    return {"total": total, "metrics": metrics}


def load_golden(db, doc_ids):
    dataset = json.loads((Path(__file__).parents[1] / "evaluation" / "golden.json").read_text(encoding="utf-8"))
    for row in dataset["cases"]:
        base_marker = f"[golden:{row['id']}]"
        marker = base_marker
        if row.get("department_code"):
            marker += f"|department={row['department_code']}"
        case = db.scalar(select(KbEvalCaseModel).where(KbEvalCaseModel.notes.startswith(base_marker)))
        if case is None:
            case = KbEvalCaseModel(notes=marker)
            db.add(case)
        case.notes = marker
        for name, value in {
            "title": row["id"], "scenario": row["scenario"], "query": row["query"],
            "expected_answer_summary": "|".join(row["facts"]),
            "expected_role": row["role"], "expected_no_answer": row["expected_no_answer"],
            "must_avoid_keywords": ",".join(row.get("forbidden_words", [])), "is_active": True,
        }.items():
            setattr(case, name, value)
        for field, keys in (
            ("expected_doc_ids", row["expected_doc_keys"]),
            ("must_cite_doc_ids", row["required_doc_keys"]),
            ("must_not_cite_doc_ids", row["forbidden_doc_keys"]),
        ):
            setattr(case, field, ",".join(str(doc_ids[key]) for key in keys))
    db.flush()
    return len(dataset["cases"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--offline", action="store_true", help="Force local rules and skip remote embeddings and generation")
    parser.add_argument("--faithfulness-labels", type=Path, help="Reviewed claims bound to SHA-256 of each exact answer")
    parser.add_argument("--corpus", choices=("golden", "all"), default="golden", help="Eval corpus: golden (92) or all (99 incl. seed cases)")
    parser.add_argument("--sample", type=int, default=None, help="Run deterministic stratified representative sample of N cases (e.g. 15)")
    parser.add_argument("--case-ids", type=str, default=None, help="Comma-separated list of eval case IDs to run")
    args = parser.parse_args()
    if args.offline:
        # This is a dedicated CLI process, so clearing its cached client keys
        # cannot affect the application server or bypass its admission limits.
        get_embedding_client().api_key = ""
        get_llm_client().api_key = ""
    with SessionLocal() as db:
        doc_ids = {}
        for doc in db.scalars(select(KbDocumentModel)):
            key = json.loads(doc.meta_json or "{}").get("seed_key")
            if key:
                doc_ids[key] = doc.id
        load_golden(db, doc_ids)
        db.commit()
        service = KnowledgeBaseService(db)
        golden_only = args.corpus == "golden"
        selected_case_ids: list[str] | None = None
        if args.case_ids:
            selected_case_ids = [item.strip() for item in args.case_ids.split(",") if item.strip()]
        elif args.sample is not None:
            all_cases = list(db.scalars(
                select(KbEvalCaseModel).where(KbEvalCaseModel.is_active.is_(True)).order_by(KbEvalCaseModel.id.asc())
            ).all())
            selected_case_ids = select_stratified_case_ids(all_cases, n=args.sample, corpus=args.corpus)

        dataset_path = Path(__file__).parents[1] / "evaluation" / "golden.json"
        dataset_bytes = dataset_path.read_bytes()
        dataset = json.loads(dataset_bytes)
        roles_report = {
            role: service.run_eval(
                Principal("user", role="admin"),
                role=role,
                golden_only=golden_only,
                case_ids=selected_case_ids,
            )
            for role in ("citizen", "department_staff")
        }
        report = {
            "dataset": dataset["version"], "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "mode": "offline" if args.offline else "configured",
            "corpus": args.corpus,
            "selected_case_ids": selected_case_ids,
            "provenance": dataset.get("provenance"), "prompt": RAG_PROMPT_VERSION, "retrieval": RETRIEVAL_VERSION,
            "response_schema": RESPONSE_SCHEMA_VERSION, "embedding_version": EMBEDDING_VERSION,
            "settings": {"top_k": service.settings.kb_rag_top_k,
                         "min_lexical_coverage": service.settings.kb_rag_min_lexical_coverage,
                         "min_vector_similarity": service.settings.kb_rag_min_vector_similarity,
                         "embedding_model": service.settings.embedding_model},
            "roles": roles_report,
            "overall": _aggregate_overall(roles_report),
        }
        if args.faithfulness_labels:
            labels = json.loads(args.faithfulness_labels.read_text(encoding="utf-8"))
            report["reviewed_faithfulness"] = apply_reviewed_faithfulness(report["roles"], labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
