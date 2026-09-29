"""Allowlisted, secret-checked source delivery. Never archive the entire working directory."""

import argparse
import io
import json
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from research_app.config import PROJECT_ROOT, settings

ROOT_FILES = {
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "vite.config.ts",
    "vite.report.config.ts",
    "index.html",
    "run.sh",
    "run.ps1",
    "Dockerfile",
    "compose.yaml",
    "THIRD_PARTY_NOTICES.txt",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    ".python-version",
    ".npmrc",
    ".prettierrc.json",
}
DIRECTORIES = {
    "backend",
    "apps",
    "packages",
    "prompts",
    "skills",
    "resources",
    "tests",
    "tools",
    "docs",
    "samples",
    "evals",
    ".github",
}


def package_project(root: Path, target: Path, secret: str = ""):
    files = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_symlink() or not path.is_file():
            continue
        if relative.parts[0] not in DIRECTORIES and str(relative) not in ROOT_FILES:
            continue
        if any(
            p in {"__pycache__", "node_modules", ".venv", ".research-data", ".git"}
            or (p.startswith(".env") and p != ".env.example")
            for p in relative.parts
        ):
            continue
        if path.suffix in {".pyc", ".pyo", ".tsbuildinfo"}:
            continue
        files.append(path)
    contents = {}
    for path in sorted(files):
        data = path.read_bytes()
        if secret and secret.encode() in data:
            raise ValueError(f"Credential found in {path.relative_to(root)}")
        if path.suffix in {".xlsx", ".docx", ".pptx"}:
            with ZipFile(io.BytesIO(data)) as archive:
                if secret and any(secret.encode() in archive.read(n) for n in archive.namelist()):
                    raise ValueError(f"Credential found in Office archive {path.name}")
        contents[path.relative_to(root).as_posix()] = data
    manifest = {name: sha256(data).hexdigest() for name, data in contents.items()}
    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            info = ZipInfo.from_file(root / name, arcname="research-agent/" + name)
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
        archive.writestr("research-agent/DELIVERY-MANIFEST.json", json.dumps(manifest, indent=2))
    return {
        "files": len(contents),
        "sha256": sha256(target.read_bytes()).hexdigest(),
        "bytes": target.stat().st_size,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT.parent / "research-agent-delivery.zip")
    args = parser.parse_args()
    result = package_project(PROJECT_ROOT, args.output, settings().api_key)
    args.output.with_suffix(".sha256").write_text(result["sha256"] + "  " + args.output.name + "\n")
    print(json.dumps(result))
