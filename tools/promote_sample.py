"""Export a real run as a replay sample without changing events or review decisions."""

import argparse
import json
from hashlib import sha256

from research_app.config import PROJECT_ROOT, settings
from research_app.domain import ResearchBundle, now_iso
from research_app.exporters import export_all
from research_app.storage import Store


def promote(name: str, run_id: str):
    if name not in {"nvda", "gold-bitcoin"}:
        raise ValueError("Unknown sample")
    config = settings()
    store = Store(config.data_dir)
    raw = (store.run_dir(run_id) / "bundle.json").read_bytes()
    bundle = ResearchBundle.model_validate_json(raw)
    bundle.mode = "sample"
    root = PROJECT_ROOT / "samples" / name
    trace = []
    cursor = 0
    while batch := store.events(run_id, cursor):
        trace.extend(batch)
        cursor = batch[-1]["seq"]
    metadata = {
        "kind": "real-run-replay",
        "run_id": run_id,
        "promoted_at": now_iso(),
        "model_requested": config.model,
        "models_observed": sorted(
            {e["payload"]["model"] for e in trace if e["kind"] == "model" and e["payload"].get("model")}
        ),
        "model_configuration_history": [
            e["payload"]
            for e in trace
            if e["kind"] == "configuration" and e["payload"].get("requested_model")
        ],
        "original_bundle_sha256": sha256(raw).hexdigest(),
        "manual_event_edits": False,
        "transformations": ["mode: live -> sample; event facts, coverage and review unchanged"],
        "completion_status": bundle.completion_status,
        "events": len(bundle.events),
        "sources": len(bundle.sources),
        "review_passed": bundle.review.get("passed", False),
    }
    root.mkdir(parents=True, exist_ok=True)
    store.save_json(root / "bundle.json", bundle.model_dump(mode="json"))
    store.save_json(root / "provenance.json", metadata)
    store.save_json(root / "trace.json", trace)
    store.save_json(
        root / "review-history.json",
        [e for e in trace if e["kind"] in {"review", "quality", "review_adjudication"}],
    )
    export_all(bundle, root / "artifacts")
    print(json.dumps({"sample": name, **metadata}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=["nvda", "gold-bitcoin"])
    parser.add_argument("run_id")
    args = parser.parse_args()
    promote(args.name, args.run_id)
