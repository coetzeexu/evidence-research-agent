"""Local-first API: one persistent worker, resumable event stream and same-origin downloads."""

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import PROJECT_ROOT, settings
from .domain import ResearchBundle, ResearchSpec
from .security import safe_error
from .storage import Store

config = settings()
store = Store(config.data_dir)
active: dict[str, asyncio.Task] = {}
active_chats: set[str] = set()
chat_jobs: set[asyncio.Task] = set()


def import_samples():
    for path in sorted((PROJECT_ROOT / "samples").glob("*/bundle.json")):
        bundle = ResearchBundle.model_validate_json(path.read_text())
        if not store.get(bundle.id):
            store.create(
                bundle.spec.title, mode="sample", spec=bundle.spec.model_dump(mode="json"), run_id=bundle.id
            )
            store.update(
                bundle.id,
                status=bundle.completion_status,
                bundle_path=str(path),
            )


async def worker():
    from .pipeline import Pipeline

    while True:
        run = store.claim_next_queued()
        if not run:
            await asyncio.sleep(0.5)
            continue
        try:
            task = asyncio.create_task(Pipeline(config, store, run["id"]).run())
            active[run["id"]] = task
            await task
        except asyncio.CancelledError:
            if store.get(run["id"])["status"] != "cancelled":
                raise
        except Exception as exc:
            message = safe_error(exc, config)
            if store.update(run["id"], expected={"running"}, status="failed", error=message):
                store.emit(run["id"], "error", message, error_type=type(exc).__name__)
        finally:
            active.pop(run["id"], None)


@asynccontextmanager
async def lifespan(app):
    import_samples()
    store.recover()
    task = asyncio.create_task(worker())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    for job in list(chat_jobs):
        job.cancel()
    await asyncio.gather(*chat_jobs, return_exceptions=True)


app = FastAPI(title="Evidence Research Agent", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])


@app.middleware("http")
async def local_boundary(request: Request, call_next):
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin mutation rejected"}, status_code=403)
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid content length"}, status_code=400)
        if length > 100_000:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data: blob:; font-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    return response


class CreateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=6000)
    spec: ResearchSpec | None = None
    refresh: bool = False
    export_reports: bool = True
    parent_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9]{1,64}$")


class ChatRequest(BaseModel):
    stream: bool = False
    message: str = Field(min_length=1, max_length=4000)
    selected_id: str | None = None


def require_run(run_id):
    run = store.get(run_id)
    if not run:
        raise HTTPException(404, "研究不存在")
    return run


def check_queue_capacity():
    queued = [r for r in store.list_runs() if r["status"] in {"queued", "running"}]
    if len(queued) >= 4:
        raise HTTPException(429, "已有四个任务正在处理，请等待或取消")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model_configured": config.model_ready,
        "model": config.model,
        "data_policy": "免费公开来源 · 按需刷新日线",
    }


@app.get("/api/runs")
def list_runs():
    return store.list_runs()


@app.post("/api/runs", status_code=202)
async def create_run(body: CreateRequest):
    if not config.model_ready:
        raise HTTPException(409, "请在本地 .env 配置模型；样例无需模型即可查看")
    if body.parent_id:
        require_run(body.parent_id)
    check_queue_capacity()
    run_id = store.create(
        body.prompt,
        spec=body.spec.model_dump(mode="json") if body.spec else None,
        parent_id=body.parent_id,
        refresh=body.refresh,
        export_reports=body.export_reports,
    )
    return {"id": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = require_run(run_id)
    # Keep local filesystem paths private.
    return {k: v for k, v in run.items() if k != "bundle_path"}


@app.get("/api/runs/{run_id}/bundle")
def get_bundle(run_id: str):
    run = require_run(run_id)
    if not run["bundle_path"]:
        raise HTTPException(409, "研究尚未完成")
    return JSONResponse(json.loads(Path(run["bundle_path"]).read_text()))


@app.get("/api/runs/{run_id}/events")
async def events(run_id: str, request: Request, after: int = 0):
    require_run(run_id)
    try:
        after = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        pass

    async def stream():
        cursor = after
        while not await request.is_disconnected():
            rows = store.events(run_id, cursor)
            for row in rows:
                cursor = row["seq"]
                yield f"id: {cursor}\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
            if len(rows) == 500:
                continue
            if require_run(run_id)["status"] not in {"running", "queued"}:
                yield "event: done\ndata: {}\n\n"
                return
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.15)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/research")
def get_research(run_id: str):
    run = require_run(run_id)
    if not run["bundle_path"]:
        raise HTTPException(409, "研究正文尚未完成核验")
    bundle = ResearchBundle.model_validate_json(Path(run["bundle_path"]).read_text())
    return (
        bundle.research.model_dump(mode="json")
        if bundle.research
        else {"status": "unassessed", "text": "", "message": "历史研究未经过正文核验"}
    )


@app.post("/api/runs/{run_id}/cancel")
async def cancel(run_id: str):
    require_run(run_id)
    if not store.update(run_id, expected={"queued", "running"}, status="cancelled"):
        raise HTTPException(409, "任务已结束")
    store.emit(run_id, "cancelled", "任务已取消")
    if run_id in active:
        active[run_id].cancel()
    return {"status": "cancelled"}


@app.post("/api/runs/{run_id}/retry")
async def retry(run_id: str):
    run = require_run(run_id)
    if run["status"] != "failed" or run["mode"] != "live":
        raise HTTPException(409, "仅失败的实时任务可从检查点恢复")
    check_queue_capacity()
    store.update(run_id, status="queued", error=None)
    return {"id": run_id}


@app.get("/api/runs/{run_id}/chat")
def chat_history(run_id: str):
    require_run(run_id)
    return store.chat_history(run_id)


@app.post("/api/runs/{run_id}/chat")
async def chat(run_id: str, body: ChatRequest):
    from .agents import AgentRuntime

    run = require_run(run_id)
    if not run["bundle_path"] or not config.model_ready:
        raise HTTPException(409, "需要已完成研究和服务端模型配置")
    if run_id in active_chats or len(active_chats) >= 4:
        raise HTTPException(409, "研究助手正在回答，请等待本轮完成")
    bundle = ResearchBundle.model_validate_json(Path(run["bundle_path"]).read_text())
    history = store.chat_history(run_id, limit=12)
    store.emit(run_id, "chat", "用户追问", role="user", text=body.message)
    active_chats.add(run_id)
    if body.stream:
        queue: asyncio.Queue = asyncio.Queue()

        async def on_chunk(text: str):
            # Defense in depth: only the successfully returned verified answer is public.
            return

        async def produce():
            try:
                await queue.put(("progress", {"message": "正在依据当前快照综合并核验回答"}))
                async with asyncio.timeout(180):
                    answer = await AgentRuntime(config, store, run_id).explain(
                        bundle, body.message, body.selected_id, history=history, on_chunk=on_chunk
                    )
                store.emit(run_id, "chat", "研究问答", role="assistant", text=answer)
                await queue.put(("delta", {"text": answer}))
                await queue.put(("done", {"answer": answer}))
            except (Exception, asyncio.CancelledError) as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                await queue.put(("error", {"message": safe_error(exc, config)}))
            finally:
                active_chats.discard(run_id)
                await queue.put(None)

        # Switching conversations/disconnecting does not discard the origin's answer.
        job = asyncio.create_task(produce())
        chat_jobs.add(job)
        job.add_done_callback(chat_jobs.discard)

        async def reply_stream():
            yield "event: accepted\ndata: {}\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if item is None:
                    return
                event, payload = item
                yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            reply_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )
    try:
        async with asyncio.timeout(180):
            answer = await AgentRuntime(config, store, run_id).explain(
                bundle, body.message, body.selected_id, history=history
            )
    except Exception as exc:
        raise HTTPException(502, safe_error(exc, config)) from None
    finally:
        active_chats.discard(run_id)
    store.emit(run_id, "chat", "研究问答", role="assistant", text=answer)
    return {"answer": answer}


@app.get("/api/runs/{run_id}/artifacts/{filename}")
def artifact(run_id: str, filename: str):
    if filename not in {"report.html", "report.xlsx", "report.pptx", "report.docx", "manifest.json"}:
        raise HTTPException(404)
    run = require_run(run_id)
    if not run["bundle_path"]:
        raise HTTPException(409, "文件尚未生成")
    if filename.startswith("report."):
        bundle = ResearchBundle.model_validate_json(Path(run["bundle_path"]).read_text())
        if filename.removeprefix("report.") not in bundle.spec.outputs:
            raise HTTPException(404, "该格式未请求")
    path = Path(run["bundle_path"]).parent / "artifacts" / filename
    if not path.is_file():
        raise HTTPException(404, "该格式未生成")
    return FileResponse(path, filename=filename)


if (PROJECT_ROOT / "dist/web").is_dir():
    app.mount("/", StaticFiles(directory=PROJECT_ROOT / "dist/web", html=True), name="web")
