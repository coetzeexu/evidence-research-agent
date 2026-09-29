"""Requested output subsets must survive the contract and dispatch unchanged."""

import json
from itertools import combinations

import pytest
from research_app import export_document, export_slides, export_workbook, exporters
from research_app.domain import ResearchSpec

FORMATS = ("html", "xlsx", "pptx", "docx")
SUBSETS = [list(c) for n in range(5) for c in combinations(FORMATS, n)]


@pytest.mark.parametrize("formats", SUBSETS)
def test_contract_and_dispatch_exact_output_subset(bundle, tmp_path, monkeypatch, formats):
    bundle.spec = ResearchSpec.model_validate({**bundle.spec.model_dump(), "outputs": formats})
    assert bundle.spec.outputs == formats
    called = []

    def writer(format):
        def write(bundle, target, *args):
            called.append(format)
            target.write_text(format)

        return write

    monkeypatch.setattr(exporters, "export_html", writer("html"))
    monkeypatch.setattr(export_workbook, "export_workbook", writer("xlsx"))
    monkeypatch.setattr(export_document, "export_document", writer("docx"))
    monkeypatch.setattr(export_slides, "export_slides", writer("pptx"))
    monkeypatch.setattr(exporters.shutil, "which", lambda _: "/test/node")
    renders = []

    def render(*args, **kwargs):
        from types import SimpleNamespace

        renders.append(True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(exporters.subprocess, "run", render)
    # Simulate re-export of a previously broader selection.
    for format in FORMATS:
        (tmp_path / f"report.{format}").write_text("stale")
    exporters.export_all(bundle, tmp_path)
    assert set(called) == set(formats)
    assert sorted(p.suffix[1:] for p in tmp_path.glob("report.*")) == sorted(formats)
    assert len(renders) == int("docx" in formats)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["requested_outputs"] == formats
    assert {n for n in manifest["files"] if n.startswith("report.")} == {f"report.{f}" for f in formats}


def test_default_report_is_html_and_duplicates_do_not_add_formats(spec):
    raw = spec.model_dump()
    raw.pop("outputs")
    assert ResearchSpec.model_validate(raw).outputs == ["html"]
    assert ResearchSpec.model_validate({**raw, "outputs": ["pptx", "pptx"]}).outputs == ["pptx"]


def test_invalid_format_is_rejected(spec):
    with pytest.raises(ValueError):
        ResearchSpec.model_validate({**spec.model_dump(), "outputs": ["pdf"]})


def test_download_rejects_stale_unrequested_artifact(bundle, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from research_app import api
    from research_app.storage import Store

    bundle.spec.outputs = ["pptx"]
    store = Store(tmp_path)
    rid = store.create("PPT only", run_id=bundle.id)
    path = store.run_dir(rid) / "bundle.json"
    store.save_json(path, bundle.model_dump(mode="json"))
    store.update(rid, bundle_path=str(path), status="complete")
    folder = path.parent / "artifacts"
    folder.mkdir()
    (folder / "report.html").write_text("old export")
    (folder / "report.pptx").write_bytes(b"requested export")
    monkeypatch.setattr(api, "store", store)
    client = TestClient(api.app)
    assert client.get(f"/api/runs/{rid}/artifacts/report.html").status_code == 404
    assert client.get(f"/api/runs/{rid}/artifacts/report.pptx").status_code == 200
