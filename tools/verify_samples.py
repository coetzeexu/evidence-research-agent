"""Offline delivery audit for the bundled snapshots and their generated files."""

import json
import re
from hashlib import sha256
from zipfile import ZipFile

from openpyxl import load_workbook
from research_app.analytics import month_end_anchors, monthly_formula_backtest, validate_bundle
from research_app.config import PROJECT_ROOT, settings
from research_app.domain import ResearchBundle, now_iso


def main():
    reports = []
    secret = settings().api_key.encode()
    for root in sorted((PROJECT_ROOT / "samples").iterdir()):
        path = root / "bundle.json"
        if not path.is_file():
            continue
        bundle = ResearchBundle.model_validate_json(path.read_text())
        folder = root / "artifacts"
        manifest = json.loads((folder / "manifest.json").read_text())
        assert validate_bundle(bundle)["passed"], root.name
        assert manifest["method_version"] == bundle.method_version
        assert manifest["data_snapshots"] == {s: d.content_hash for s, d in bundle.datasets.items()}
        for name, entry in manifest["files"].items():
            content = (folder / name).read_bytes()
            assert sha256(content).hexdigest() == entry["sha256"], name
            assert entry["bytes"] == len(content), name
            assert not secret or secret not in content, f"Credential found in {name}"
        embedded = re.search(r'id="report-data">(.*?)</script>', (folder / "report.html").read_text(), re.S)
        assert embedded and json.loads(embedded.group(1)) == bundle.model_dump(mode="json")
        assert json.loads((folder / "research-data.json").read_text()) == bundle.model_dump(mode="json")
        book = load_workbook(folder / "report.xlsx", data_only=True)
        errors = [
            (sheet.title, cell.coordinate)
            for sheet in book
            for row in sheet
            for cell in row
            if cell.data_type == "e"
        ]
        assert not errors, errors
        anchors = (
            bundle.comparison.get("anchors", [])
            if len(bundle.spec.symbols) > 1
            else month_end_anchors(bundle.datasets, bundle.spec.symbols, bundle.spec.start, bundle.spec.end)
        )
        expected = monthly_formula_backtest(anchors, bundle.spec)
        if expected["rows"]:
            assert abs(book["Overview"]["B17"].value - expected["metrics"]["total_return"]) < 1e-10
            assert abs(book["Overview"]["B18"].value - expected["metrics"]["max_drawdown"]) < 1e-10
        structures = {}
        for name in ["report.docx", "report.pptx"]:
            with ZipFile(folder / name) as archive:
                for item in archive.namelist():
                    if item.endswith((".xml", ".rels")):
                        content = archive.read(item)
                        assert not secret or secret not in content, f"Credential found in {name}"
                structures[name] = {"zip_valid": archive.testzip() is None}
                if name.endswith("pptx"):
                    structures[name]["native_charts"] = len(
                        [p for p in archive.namelist() if re.fullmatch(r"ppt/charts/chart\d+.xml", p)]
                    )
                    structures[name]["slides"] = len(
                        [p for p in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+.xml", p)]
                    )
        reports.append(
            {
                "sample": root.name,
                "passed": True,
                "method_version": bundle.method_version,
                "events": len(bundle.events),
                "sources": len(bundle.sources),
                "manifest_files": len(manifest["files"]),
                "workbook_errors": errors,
                "structures": structures,
            }
        )
    result = {
        "checked_at": now_iso(),
        "checks": reports,
        "scope": "Snapshot/HTML equality, manifest hashes, cached Excel formulas, OOXML structure. Not browser or Office visual acceptance.",
    }
    (PROJECT_ROOT / "evals/sample-validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
