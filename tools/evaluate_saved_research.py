"""Development-only text recheck of saved evidence; never counts as a full live acceptance run."""

import argparse
import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

from evaluate_text_research import check_text, code_hash
from research_app.agents import AgentRuntime
from research_app.config import PROJECT_ROOT, settings
from research_app.domain import ResearchBundle
from research_app.research_text import NarrativeService, research_questions
from research_app.storage import Store


async def main(run_dir, suite):
    if not suite.isalnum():
        raise ValueError("suite must be alphanumeric")
    output = PROJECT_ROOT / "evals/boundary-probes" / f"{suite}.json"
    if output.exists():
        raise ValueError("Keep prior probe records; choose a new suite")
    source = run_dir.resolve()
    with sqlite3.connect((source.parent.parent / "research.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        request = db.execute("select prompt from runs where id=?", (source.name,)).fetchone()[0]
    config = replace(settings(), data_dir=PROJECT_ROOT.parent.parent / "work/text-boundary-probes" / suite)
    store = Store(config.data_dir)
    rid = store.create(request, export_reports=False)
    root = store.run_dir(rid)
    shutil.copyfile(source / "research-evidence.json", root / "research-evidence.json")
    bundle = ResearchBundle.model_validate_json((source / "bundle.json").read_text())
    bundle.id = rid
    questions = bundle.research.questions if bundle.research else research_questions(bundle.spec)
    runtime = AgentRuntime(config, store, rid)
    frozen = code_hash()
    try:
        bundle.research = await NarrativeService(runtime).compose(bundle, questions, request)
    finally:
        runtime.budget.stop()
    store.save_json(root / "bundle.json", bundle.model_dump(mode="json"))
    result = {
        "mode": "saved-evidence-development-probe",
        "name": suite,
        "run_id": rid,
        "source_run": source.name,
        "code_hash": frozen,
        "code_unchanged": frozen == code_hash(),
        "checks": check_text(bundle, runtime.texts),
        "status": bundle.research.status,
        "budget": runtime.budget.snapshot(),
        "unanswered": [q.model_dump() for q in bundle.research.questions if q.status != "answered"],
    }
    output.parent.mkdir(exist_ok=True)
    store.save_json(output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--suite", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.run_dir, args.suite))
