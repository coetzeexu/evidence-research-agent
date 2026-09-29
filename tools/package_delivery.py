"""Allowlisted, secret-checked source delivery. Never archive the entire working directory."""

import argparse
import io
import json
import os
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
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


def delivery_files(root: Path):
    files = []
    candidates = [root / name for name in sorted(ROOT_FILES)]
    candidates.extend(p for folder in sorted(DIRECTORIES) for p in (root / folder).rglob("*"))
    for path in candidates:
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
    return sorted(files)


def verify_delivery(target: Path, source: Path | None = None):
    """Check every member, then optionally prove equality with the current source tree."""
    with ZipFile(target) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive members")
        for name in names:
            parts = PurePosixPath(name).parts
            if (
                not name.startswith("research-agent/")
                or ".." in parts
                or "\\" in name
                or any(p.startswith(".env") and p != ".env.example" for p in parts)
                or any(p in {".git", ".venv", "node_modules", ".research-data"} for p in parts)
                or (archive.getinfo(name).external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError(f"Unsafe archive member: {name}")
        manifest = json.loads(archive.read("research-agent/DELIVERY-MANIFEST.json"))
        expected = {"research-agent/" + name for name in manifest} | {
            "research-agent/DELIVERY-MANIFEST.json",
            "research-agent/DELIVERY-INFO.json",
        }
        if set(names) != expected:
            raise ValueError("Archive member set differs from manifest")
        for name, expected_hash in manifest.items():
            if sha256(archive.read("research-agent/" + name)).hexdigest() != expected_hash:
                raise ValueError(f"Archive hash mismatch: {name}")
        fingerprint = sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        info = json.loads(archive.read("research-agent/DELIVERY-INFO.json"))
        if info.get("source_tree_sha256") != fingerprint:
            raise ValueError("Source tree fingerprint mismatch")
        if source is not None:
            current = {
                path.relative_to(source).as_posix(): sha256(path.read_bytes()).hexdigest()
                for path in delivery_files(source)
            }
            if current != manifest:
                different = sorted(
                    n for n in current.keys() | manifest.keys() if current.get(n) != manifest.get(n)
                )
                raise ValueError("Stale delivery differs from source: " + ", ".join(different[:15]))
        if (
            "run.sh" in manifest
            and not (archive.getinfo("research-agent/run.sh").external_attr >> 16) & 0o111
        ):
            raise ValueError("Launcher execute permission missing")
    return {
        "files": len(manifest),
        "sha256": sha256(target.read_bytes()).hexdigest(),
        "bytes": target.stat().st_size,
        "source_tree_sha256": fingerprint,
        "source_matches": source is not None,
        "verified": True,
    }


def source_revision(root):
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True
        )
        return {"git_commit": revision.stdout.strip(), "working_tree_dirty": bool(status.stdout.strip())}
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "working_tree_dirty": None}


def package_project(root: Path, target: Path, secret: str = ""):
    files = delivery_files(root)
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
    info = {
        "schema_version": 1,
        **source_revision(root),
        "source_tree_sha256": sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        "scope": "Exact allowlisted source and artifact bytes; historical evaluation records keep their original versions.",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.stem + "-", suffix=".zip", dir=target.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for name, data in contents.items():
                entry = ZipInfo.from_file(root / name, arcname="research-agent/" + name)
                entry.compress_type = ZIP_DEFLATED
                archive.writestr(entry, data)
            archive.writestr("research-agent/DELIVERY-MANIFEST.json", json.dumps(manifest, indent=2))
            archive.writestr("research-agent/DELIVERY-INFO.json", json.dumps(info, indent=2))
        result = verify_delivery(temporary, root)
        os.replace(temporary, target)
        return result
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT.parent / "research-agent-delivery.zip")
    parser.add_argument("--verify", type=Path, help="Verify a ZIP against its manifest and current source")
    args = parser.parse_args()
    result = (
        verify_delivery(args.verify, PROJECT_ROOT)
        if args.verify
        else package_project(PROJECT_ROOT, args.output, settings().api_key)
    )
    if not args.verify:
        args.output.with_suffix(".sha256").write_text(result["sha256"] + "  " + args.output.name + "\n")
    print(json.dumps(result))
