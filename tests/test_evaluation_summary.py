"""Acceptance summaries must not silently select only successful attempts."""

import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).parents[1] / "tools/summarize_text_evaluation.py"
spec = importlib.util.spec_from_file_location("evaluation_summary", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_matrix(root):
    folder = root / "TestSuite"
    folder.mkdir()
    results = []
    for case, count in module.EXPECTED_CASES.items():
        for index in range(count):
            rid = f"{case}{index}"
            checks = dict.fromkeys(module.REQUIRED_CHECKS, True)
            checks["requested_execution" if case.startswith("gold-") else "explicit_events_preserved"] = True
            row = {
                "case": case,
                "run_id": rid,
                "started_at": rid,
                "checks": checks,
                "automated_pass": True,
                "mode": "live-end-to-end",
                "code_hash": "frozen-code-hash",
                "code_unchanged": True,
                "bundle_hash": f"bundle-{rid}",
            }
            result_path = folder / f"{rid}.result.json"
            result_path.write_text(json.dumps(row))
            (folder / f"{rid}.content-audit.json").write_text(
                json.dumps(
                    {"run_id": rid, "bundle_hash": f"bundle-{rid}", "content_pass": True, "issues": []}
                )
            )
            results.append((result_path, row))
    return results


def test_eight_distinct_live_runs_and_audits_required(tmp_path):
    write_matrix(tmp_path)
    summary = module.summarize(tmp_path, ["TestSuite"])
    assert summary["acceptance_passed"]
    assert summary["automated_pass_count"] == summary["independently_accepted_count"] == 8
    audit = next((tmp_path / "TestSuite").glob("*.content-audit.json"))
    audit.unlink()
    assert not module.summarize(tmp_path, ["TestSuite"])["acceptance_passed"]


@pytest.mark.parametrize(
    "failure", ["count", "check", "missing", "snapshot", "version", "duplicate", "audit", "audit_snapshot"]
)
def test_reject_incomplete_or_mixed_acceptance(tmp_path, failure):
    rows = write_matrix(tmp_path)
    path, row = rows[0]
    if failure == "count":
        path.unlink()
    else:
        if failure == "check":
            row["checks"]["complete"] = False
        elif failure == "missing":
            del row["checks"]["required_questions"]
        elif failure == "snapshot":
            row["mode"] = "frozen-text"
        elif failure == "version":
            row["code_hash"] = "other-version"
        elif failure == "duplicate":
            row["run_id"] = rows[1][1]["run_id"]
        elif failure == "audit":
            (path.parent / f"{row['run_id']}.content-audit.json").write_text(
                json.dumps(
                    {
                        "run_id": row["run_id"],
                        "bundle_hash": row["bundle_hash"],
                        "content_pass": True,
                        "issues": [{"severity": "critical"}],
                    }
                )
            )
        elif failure == "audit_snapshot":
            row["bundle_hash"] = "modified-after-audit"
        path.write_text(json.dumps(row))
    assert not module.summarize(tmp_path, ["TestSuite"])["acceptance_passed"]
