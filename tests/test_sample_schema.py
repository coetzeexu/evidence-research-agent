import json

import pytest
from research_app.research_contract import ResearchAssessment
from research_app.samples import canonical_sample, replay_sample
from research_app.storage import Store


def test_legacy_migration_cannot_inherit_new_verified_status(bundle):
    raw = bundle.model_dump(mode="json")
    raw.pop("research")
    raw.update(schema_version="1.0", method_version="2026.09.3")
    current = canonical_sample(raw)
    assert current.schema_version == "1.1" and current.method_version == "2026.09.3"
    assert current.research is None
    assert "research" in current.model_dump()
    assert canonical_sample(current.model_dump()).model_dump() == current.model_dump()
    with pytest.raises(ValueError, match="不能静默降级"):
        canonical_sample({**raw, "schema_version": "999.0"})


def test_assessed_snapshot_retains_real_research_fields(bundle):
    bundle.research = ResearchAssessment(status="partial", text="真实核验正文与缺口")
    assert canonical_sample(bundle.model_dump()).research == bundle.research


def test_replay_synchronizes_snapshot_after_export_only(bundle, tmp_path, monkeypatch):
    from research_app import exporters

    root = tmp_path / "sample"
    root.mkdir()
    path = root / "bundle.json"
    raw = bundle.model_dump(mode="json")
    raw.pop("research")
    raw["schema_version"] = "1.0"
    path.write_text(json.dumps(raw))
    original = path.read_bytes()
    exported = []
    monkeypatch.setattr(exporters, "export_all", lambda b, target: exported.append(b.model_dump(mode="json")))
    store = Store(tmp_path / "store")
    replay_sample(root, store, tmp_path / "custom")
    assert path.read_bytes() == original
    replay_sample(root, store)
    assert json.loads(path.read_text()) == exported[-1]
    assert json.loads((root / "schema-migration.json").read_text())["research_status"] == "unassessed"

    def fail(*args):
        raise ValueError("export failed")

    monkeypatch.setattr(exporters, "export_all", fail)
    path.write_bytes(original)
    with pytest.raises(ValueError, match="export failed"):
        replay_sample(root, store)
    assert path.read_bytes() == original
