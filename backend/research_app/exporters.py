"""All artifacts consume the same validated ResearchBundle. No model keys enter this layer."""

import json
import shutil
import subprocess
from base64 import b64encode
from hashlib import sha256
from html import escape
from pathlib import Path

from .analytics import validate_bundle
from .config import PROJECT_ROOT
from .domain import ResearchBundle, now_iso


def safe_json(value) -> str:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def export_html(bundle: ResearchBundle, target: Path):
    assets = PROJECT_ROOT / "dist/report"
    if not (assets / "report.js").exists():
        raise RuntimeError("请先执行 npm run build，生成本地离线图表资源")
    script = (assets / "report.js").read_text().replace("</script", "<\\/script")
    style = (assets / "report.css").read_text()
    notice = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.txt").read_text().replace("--", "- -")
    signature = b64encode(sha256(script.encode()).digest()).decode()
    csp = f"default-src 'none'; script-src 'sha256-{signature}'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
    target.write_text(
        f'<!doctype html><!--\n{notice}\n--><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}"><meta name="referrer" content="no-referrer">'
        f'<title>{escape(bundle.spec.title)} · Evidence</title><style>{style}</style></head><body><div id="root"></div>'
        f'<script type="application/json" id="report-data">{safe_json(bundle.model_dump(mode="json"))}</script>'
        f"<script>{script}</script></body></html>"
    )


def export_all(bundle: ResearchBundle, directory: Path):
    validation = validate_bundle(bundle)
    if not validation["passed"]:
        raise ValueError("导出前引用或数值校验失败")
    directory.mkdir(parents=True, exist_ok=True)
    payload = directory / "research-data.json"
    payload.write_text(bundle.model_dump_json(indent=2))
    formats = set(bundle.spec.outputs)
    if "html" in formats:
        export_html(bundle, directory / "report.html")
    if "xlsx" in formats:
        from .export_workbook import export_workbook

        export_workbook(bundle, directory / "report.xlsx")
    if "docx" in formats:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Word/PPT 图表导出需要 Node.js 22+")
        result = subprocess.run(
            [node, str(PROJECT_ROOT / "tools/render-charts.mjs"), str(payload), str(directory / "charts")],
            cwd=PROJECT_ROOT,
            capture_output=True,
            timeout=90,
            text=True,
        )
        if result.returncode:
            raise RuntimeError("图表离线渲染失败：请确认 npm ci 已完成")
    if "docx" in formats:
        from .export_document import export_document

        export_document(bundle, directory / "report.docx", directory / "charts")
    if "pptx" in formats:
        from .export_slides import export_slides

        export_slides(bundle, directory / "report.pptx")
    # Re-exporting a narrower selection must not expose stale reports from a
    # previous export. Only remove our known generated files, after success.
    for extension in {"html", "xlsx", "pptx", "docx"} - formats:
        (directory / f"report.{extension}").unlink(missing_ok=True)
    if "docx" not in formats and (directory / "charts").is_dir():
        shutil.rmtree(directory / "charts")
    manifest = {
        "run_id": bundle.id,
        "generated_at": now_iso(),
        "schema_version": bundle.schema_version,
        "method_version": bundle.method_version,
        "research_status": bundle.research.status if bundle.research else "unassessed",
        "requested_outputs": bundle.spec.outputs,
        "validation": validation,
        "data_snapshots": {s: d.content_hash for s, d in bundle.datasets.items()},
        "files": {
            p.name: {"sha256": sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
            for p in directory.iterdir()
            if p.is_file() and p.name != "manifest.json"
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
