"""Opt-in live semantic evaluation. Uses the configured server model; never prints credentials."""

import asyncio
import json

from research_app.agents import AgentRuntime
from research_app.config import PROJECT_ROOT, settings
from research_app.security import safe_error
from research_app.storage import Store


async def main():
    config = settings()
    store = Store(config.data_dir)
    cases = json.loads((PROJECT_ROOT / "evals/cases.json").read_text())
    semaphore = asyncio.Semaphore(2)

    async def evaluate(case):
        async with semaphore:
            rid = store.create(case["prompt"], mode="evaluation")
            store.update(rid, status="running")
            try:
                parsed = await AgentRuntime(config, store, rid).parse(case["prompt"])
                actual = parsed.model_dump(mode="json")
                expected = {k: v for k, v in case.items() if k != "prompt"}
                if case.get("clarification"):
                    passed = parsed.needs_clarification
                else:
                    passed = parsed.spec is not None and all(
                        getattr(parsed.spec, k) == v for k, v in expected.items()
                    )
                store.update(rid, status="complete")
                return {"prompt": case["prompt"], "expected": expected, "actual": actual, "passed": passed}
            except Exception as exc:
                store.update(rid, status="failed", error=safe_error(exc, config))
                return {"prompt": case["prompt"], "passed": False, "error": safe_error(exc, config)}

    results = await asyncio.gather(*(evaluate(c) for c in cases))
    report = {
        "model_requested": config.model,
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "cases": results,
    }
    output = PROJECT_ROOT / "evals/results.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
