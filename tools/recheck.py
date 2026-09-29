"""Recheck a saved run after provider / extraction fixes; preserves every operation in its trace."""

import argparse
import asyncio
import json

from research_app.config import settings
from research_app.pipeline import Pipeline
from research_app.storage import Store


async def main(run_id: str, repair: str):
    config = settings()
    store = Store(config.data_dir)
    run = store.get(run_id)
    if not run or not run["spec"]:
        raise ValueError("Run not found")
    p = Pipeline(config, store, run_id, export=False)
    # A new bounded recheck gets its own explicit budget, never disguises itself as a fresh run.
    p.runtime.search_count = 0
    p.runtime.read_count = 0
    p.runtime.persist()
    store.emit(run_id, "recheck", "开发验证：重新核验来源与提取", reason=repair)
    state = {"run_id": run_id, "spec": run["spec"], "repair": repair, "repair_round": 0}
    await p.research(state)
    await p.analyze(state)
    update = await p.review(state)
    state.update(update)
    if state.get("repair"):
        await p.research(state)
        await p.analyze(state)
        await p.review(state)
    await p.render(state)
    print(json.dumps({"run_id": run_id, "status": store.get(run_id)["status"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("repair")
    args = parser.parse_args()
    asyncio.run(main(args.run_id, args.repair))
