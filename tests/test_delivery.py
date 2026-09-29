import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest
from research_app.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("delivery", PROJECT_ROOT / "tools/package_delivery.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_delivery_excludes_private_state_and_checks_credential(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    for name in [
        "README.md",
        ".env",
        ".env.example",
        "backend/app.py",
        "tools/.env",
        ".research-data/private.json",
        "node_modules/private.js",
    ]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("non-sensitive")
    target = tmp_path / "delivery.zip"
    result = module.package_project(root, target)
    with ZipFile(target) as archive:
        names = archive.namelist()
        assert "research-agent/.env.example" in names
        assert "research-agent/backend/app.py" in names
        assert not any(Path(n).name == ".env" or ".research-data" in n or "node_modules" in n for n in names)
    assert result["files"] == 3
    (root / "README.md").write_text("example-long-credential-DO-NOT-SHIP")
    with pytest.raises(ValueError, match="Credential"):
        module.package_project(root, target, "example-long-credential-DO-NOT-SHIP")


def test_delivery_inspects_office_zip_contents(tmp_path):
    root = tmp_path / "project"
    folder = root / "samples"
    folder.mkdir(parents=True)
    with ZipFile(folder / "test.docx", "w") as archive:
        archive.writestr("word/document.xml", "private-key-hidden-in-compression")
    with pytest.raises(ValueError, match="Credential"):
        module.package_project(root, tmp_path / "delivery.zip", "private-key-hidden-in-compression")


def test_delivery_preserves_launcher_permissions(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    launcher = root / "run.sh"
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    target = tmp_path / "delivery.zip"
    module.package_project(root, target)
    with ZipFile(target) as archive:
        assert (archive.getinfo("research-agent/run.sh").external_attr >> 16) & 0o111 == 0o111


@pytest.mark.parametrize("mutation", ["edit", "add", "delete"])
def test_verify_rejects_stale_release_even_with_valid_internal_hashes(tmp_path, mutation):
    root = tmp_path / "project"
    (root / "backend").mkdir(parents=True)
    path = root / "backend/app.py"
    path.write_text("original")
    target = tmp_path / "delivery.zip"
    module.package_project(root, target)
    assert module.verify_delivery(target, root)["source_matches"]
    if mutation == "edit":
        path.write_text("changed")
    elif mutation == "add":
        (root / "backend/research_text.py").write_text("new required module")
    else:
        path.unlink()
    with pytest.raises(ValueError, match="Stale delivery"):
        module.verify_delivery(target, root)


def test_verify_rejects_tampering_and_unlisted_files(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("original")
    target = tmp_path / "delivery.zip"
    module.package_project(root, target)
    tampered = tmp_path / "tampered.zip"
    with ZipFile(target) as original, ZipFile(tampered, "w") as changed:
        for entry in original.infolist():
            changed.writestr(
                entry, b"modified" if entry.filename.endswith("README.md") else original.read(entry)
            )
    with pytest.raises(ValueError, match="hash mismatch"):
        module.verify_delivery(tampered)
    with ZipFile(target, "a") as archive:
        archive.writestr("research-agent/unlisted.txt", "unexpected")
    with pytest.raises(ValueError, match="member set"):
        module.verify_delivery(target)


def test_pack_failure_keeps_previous_good_zip(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    path = root / "README.md"
    path.write_text("original")
    target = tmp_path / "delivery.zip"
    module.package_project(root, target)
    previous = target.read_bytes()
    path.write_text("sensitive-do-not-ship")
    with pytest.raises(ValueError, match="Credential"):
        module.package_project(root, target, "sensitive-do-not-ship")
    assert target.read_bytes() == previous
