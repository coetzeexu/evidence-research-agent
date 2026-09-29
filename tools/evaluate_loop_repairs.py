"""One bounded transcription repair per frozen failure; no searches or report exports."""

import asyncio
import json
from dataclasses import replace

from research_app.agents import AgentRuntime
from research_app.budget import ExecutionBudget
from research_app.config import PROJECT_ROOT, settings
from research_app.domain import digest, now_iso
from research_app.research_contract import NarrativeDraft, NarrativeReview, ResearchMetric
from research_app.research_logic import repair_numeric_transcription, verify_relationships
from research_app.storage import Store


async def main():
    config = replace(settings(), data_dir=PROJECT_ROOT / ".research-data/loop-repair-eval")
    store = Store(config.data_dir)
    cases = json.loads((PROJECT_ROOT / "evals/loop-repair-cases.json").read_text())
    results = []
    for case in cases:
        rid = store.create("Frozen numeric transcription repair", export_reports=False)
        runtime = AgentRuntime(config, store, rid)
        budget = ExecutionBudget(store, rid, seconds=120, calls=2)
        budget.start()
        draft = NarrativeDraft.model_validate(case["draft"])
        review = NarrativeReview.model_validate(case["review"])
        metrics = {m["id"]: ResearchMetric.model_validate(m) for m in case["metrics"]}
        original = digest(draft.model_dump())
        result, audit = await repair_numeric_transcription(runtime, draft, review, metrics, budget)
        budget.stop()
        errors, checks = verify_relationships(draft, result, metrics)
        record = {
            "original_run_id": case["original_run_id"],
            "run_id": rid,
            "passed": not errors,
            "draft_unchanged": original == digest(draft.model_dump()),
            "verdicts_unchanged": [v.verdict for v in review.claims] == [v.verdict for v in result.claims],
            "remaining_errors": errors,
            "checks": checks,
            "audit": audit,
            "budget": budget.snapshot(),
        }
        results.append(record)
        print(
            json.dumps({k: record[k] for k in ("original_run_id", "passed", "draft_unchanged")}), flush=True
        )
    output = {
        "at": now_iso(),
        "scope": "One frozen failed finding per partial run; not a new full research acceptance",
        "prompt_hash": digest(runtime.prompts["numeric-review"]),
        "results": results,
    }
    (PROJECT_ROOT / "evals/loop-repair-validation.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
