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
