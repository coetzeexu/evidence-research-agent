"""Offline schema migration never invents a new analysis or verification status."""

import json
from hashlib import sha256

from .domain import ResearchBundle, now_iso


def canonical_sample(payload):
    current = ResearchBundle.model_fields["schema_version"].default
    if payload.get("schema_version", "1.0") not in {"1.0", current}:
        raise ValueError("样例 schema 版本不受支持，不能静默降级")
    bundle = ResearchBundle.model_validate(payload)
    bundle.schema_version = current
    # The old calculation version remains accurate; replay does not recompute it.
    return bundle


def replay_sample(root, store, output=None):
    from .exporters import export_all

    path = root / "bundle.json"
    raw = path.read_bytes()
    payload = json.loads(raw)
    bundle = canonical_sample(payload)
    canonical = bundle.model_dump(mode="json")
    target = output or root / "artifacts"
    export_all(bundle, target)
    if output is None:
        # Commit the canonical snapshot only after successful export. A failed export
        # remains detectable by verify_samples; never bless inconsistent artifacts.
        store.save_json(path, canonical)
        if payload != canonical:
            store.save_json(
                root / "schema-migration.json",
                {
                    "at": now_iso(),
                    "original_sha256": sha256(raw).hexdigest(),
                    "from_schema": payload.get("schema_version", "1.0"),
                    "to_schema": bundle.schema_version,
                    "method_version": bundle.method_version,
                    "research_status": bundle.research.status if bundle.research else "unassessed",
                    "recomputed_analysis": False,
                    "model_called": False,
                    "note": "Canonical fields and offline artifacts only; no new research or verification is implied.",
                },
            )
    return target
