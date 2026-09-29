"""Verify the final ZIP, boot its extracted launcher without keys, and check downloads.

Run from the source checkout with --archive ZIP --work-dir NEW_DIRECTORY --output JSON.
No browser, model, or external research service is used. Dependency installation needs network.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import time
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

import httpx
from package_delivery import verify_delivery
from research_app.config import PROJECT_ROOT


def check_delivery(archive, work, output):
    verified = verify_delivery(archive, PROJECT_ROOT)
    if work.exists():
        raise ValueError("Use a new work directory; do not reuse installed dependencies")
    work.mkdir(parents=True)
    with ZipFile(archive) as zipped:
        zipped.extractall(work)
        # zipfile extraction does not restore executable permissions.
        root = work / "research-agent"
        (root / "run.sh").chmod(zipped.getinfo("research-agent/run.sh").external_attr >> 16 & 0o777)
        manifest = json.loads(zipped.read("research-agent/DELIVERY-MANIFEST.json"))
    assert all(sha256((root / name).read_bytes()).hexdigest() == value for name, value in manifest.items())
    assert not (root / ".env").exists() and not (root / ".venv").exists()
    assert not (root / "node_modules").exists()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LLM_", "OPENAI_", "RESEARCH_"))
        and k not in {"VIRTUAL_ENV", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT"}
    }
    env.update(
        RESEARCH_PORT=str(port), RESEARCH_DATA_DIR=str(work / "runtime"), LLM_API_KEY="", OPENAI_API_KEY=""
    )
    started = time.monotonic()
    record = {"archive": archive.name, "package": verified, "browser_opened": False, "model_called": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    launcher = ["powershell", "-File", ".\\run.ps1"] if os.name == "nt" else ["./run.sh"]
    with (work / "launcher.log").open("w") as log:
        process = subprocess.Popen(
            launcher, cwd=root, env=env, stdout=log, stderr=log, start_new_session=True
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5) as client:
                while time.monotonic() - started < 240:
                    if process.poll() is not None:
                        raise RuntimeError("Launcher exited; inspect launcher.log")
                    try:
                        response = client.get("/api/health")
                        if response.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.5)
                else:
                    raise TimeoutError("Clean launcher did not become healthy in 240 seconds")
                health = response.json()
                assert health["status"] == "ok" and health["model_configured"] is False
                index = client.get("/")
                assert index.status_code == 200 and 'id="root"' in index.text
                rows = client.get("/api/runs").json()
                assert len(rows) == 2
                downloads = []
                for row in rows:
                    rid = row["id"]
                    bundle = client.get(f"/api/runs/{rid}/bundle")
                    assert bundle.status_code == 200
                    details = client.get(f"/api/runs/{rid}/artifacts/manifest.json").json()
                    formats = bundle.json()["spec"]["outputs"]
                    assert details["requested_outputs"] == formats
                    for omitted in {"html", "xlsx", "pptx", "docx"} - set(formats):
                        assert client.get(f"/api/runs/{rid}/artifacts/report.{omitted}").status_code == 404
                    for name in (f"report.{fmt}" for fmt in formats):
                        result = client.get(f"/api/runs/{rid}/artifacts/{name}")
                        assert result.status_code == 200
                        digest = sha256(result.content).hexdigest()
                        assert digest == details["files"][name]["sha256"]
                        downloads.append(
                            {"run_id": rid, "file": name, "bytes": len(result.content), "sha256": digest}
                        )
                refused = client.post("/api/runs", json={"prompt": "No model credentials in delivery check"})
                assert refused.status_code == 409
                record.update(
                    passed=True,
                    health=health,
                    downloads=downloads,
                    samples=2,
                    no_key_request_rejected=True,
                    unrequested_formats_rejected=True,
                )
            # Re-run the regression suite from the extracted checkout and its own venv.
            for name, command in (
                ("backend", ["uv", "run", "pytest", "-q"]),
                ("frontend", ["npm", "test", "--", "--run"]),
            ):
                completed = subprocess.run(
                    command, cwd=root, env=env, capture_output=True, text=True, timeout=120
                )
                (work / f"{name}-tests.log").write_text(completed.stdout + completed.stderr)
                if completed.returncode:
                    raise RuntimeError(f"Extracted {name} regression failed")
                record[name + "_tests_passed"] = True
        except Exception as exc:
            record.update(passed=False, error=type(exc).__name__)
            raise
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    process.terminate()
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            record["elapsed_seconds"] = round(time.monotonic() - started, 2)
            output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    check_delivery(args.archive.resolve(), args.work_dir.resolve(), args.output.resolve())
