import argparse
import asyncio
import json
from pathlib import Path

from .config import settings
from .domain import ResearchBundle, ResearchSpec
from .storage import Store


def main():
    parser = argparse.ArgumentParser(description="Evidence research agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    run = sub.add_parser("run")
    run.add_argument("prompt", nargs="?", default="")
    run.add_argument("--spec", type=Path)
    run.add_argument("--no-export", action="store_true")
    show = sub.add_parser("show", help="Read verified research text without rendering a report")
    show.add_argument("run_id")
    show.add_argument("--format", choices=["text", "json"], default="text")
    export = sub.add_parser("export")
    export.add_argument("run_id")
    replay = sub.add_parser("replay", help="Regenerate bundled artifacts without a model or network")
    replay.add_argument("sample", choices=["nvda", "gold-bitcoin"])
    replay.add_argument("--output", type=Path)
    sub.add_parser("status")
    args = parser.parse_args()
    config = settings()
    store = Store(config.data_dir)
    if args.command == "serve":
        import uvicorn

        uvicorn.run("research_app.api:app", host=config.host, port=config.port)
    elif args.command == "run":
        from .pipeline import Pipeline

        spec = (
            ResearchSpec.model_validate_json(args.spec.read_text()).model_dump(mode="json")
            if args.spec
            else None
        )
        run_id = store.create(args.prompt or spec["title"], spec=spec, export_reports=not args.no_export)
        print(json.dumps({"run_id": run_id, "status": "started"}), flush=True)
        try:
            asyncio.run(Pipeline(config, store, run_id, export=not args.no_export).run())
        except Exception:
            print(
                json.dumps(
                    {"run_id": run_id, "status": "failed", "error": store.get(run_id)["error"]},
                    ensure_ascii=False,
                )
            )
            raise SystemExit(1) from None
        print(json.dumps({"run_id": run_id, "status": store.get(run_id)["status"]}, ensure_ascii=False))
    elif args.command == "show":
        saved = store.get(args.run_id)
        if not saved or not saved["bundle_path"]:
            raise SystemExit("研究正文尚未完成核验")
        bundle = ResearchBundle.model_validate_json(Path(saved["bundle_path"]).read_text())
        if not bundle.research:
            raise SystemExit("历史研究未经过正文核验（unassessed）")
        print(bundle.research.text if args.format == "text" else bundle.research.model_dump_json(indent=2))
    elif args.command == "replay":
        from .config import PROJECT_ROOT
        from .exporters import export_all

        root = PROJECT_ROOT / "samples" / args.sample
        bundle = ResearchBundle.model_validate_json((root / "bundle.json").read_text())
        target = args.output or root / "artifacts"
        export_all(bundle, target)
        print(f"Artifacts regenerated: {target}")
    elif args.command == "export":
        from .exporters import export_all

        run = store.get(args.run_id)
        if not run or not run["bundle_path"]:
            raise SystemExit("研究结果不存在")
        bundle = ResearchBundle.model_validate_json(Path(run["bundle_path"]).read_text())
        export_all(bundle, store.run_dir(args.run_id) / "artifacts")
        store.update(args.run_id, status=bundle.completion_status)
        print("Export complete")
    elif args.command == "status":
        print(
            json.dumps(
                {"model": config.model, "configured": config.model_ready, "runs": store.list_runs()},
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
