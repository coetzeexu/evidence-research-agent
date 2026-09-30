"""Necessary coverage checks, independent of the model's overall answered verdict.

These checks prove located coverage, not semantic truth. Source and meaning
review must still approve every finding before it can be used here.
"""

import re

PRODUCT = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Za-z]*(?:-)?\d+[A-Za-z0-9-]*(?![A-Za-z0-9])")
TOKEN = re.compile(r"\{\{([^{}\s]+)\}\}")
DIMENSIONS = {"cost": "成本", "weights": "权重", "frequency": "再平衡频率", "period": "分段"}
OUTCOMES = {"total_return", "cagr", "volatility", "max_drawdown"}


def coverage_requirements(question):
    if question.kind == "sensitivity":
        return [
            {"id": dimension, "description": f"{label}的实际结果比较，引用至少两个情景的同名收益或风险指标"}
            for dimension, label in DIMENSIONS.items()
        ]
    # Only literal product identifiers in a user-required event, never invented
    # by the reviewer. B200 and GB200 must remain distinct.
    return [
        {"id": f"product:{token}", "description": f"{token} 的明确事实，正文与原文引文均需对应"}
        for token in dict.fromkeys(PRODUCT.findall(question.required_event))
    ]


def mentions(text, token):
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", text, re.I))


def has_scenario_comparison(quote, dimension, rows):
    outcomes = {}
    for mid in TOKEN.findall(quote):
        parts = mid.split(".")
        if len(parts) != 3 or parts[-1] not in OUTCOMES:
            continue
        if parts[:2] == ["execution", "portfolio"] and dimension != "period":
            outcomes.setdefault(parts[-1], set()).add("baseline")
        elif parts[0] == "sensitivity" and parts[1].isdigit() and int(parts[1]) < len(rows):
            index = int(parts[1])
            row = rows[index]
            if row["dimension"] == dimension:
                outcomes.setdefault(parts[-1], set()).add(index)
            elif row["dimension"] == "baseline" and dimension != "period":
                outcomes.setdefault(parts[-1], set()).add("baseline")
    return any(len(scenarios) >= 2 for scenarios in outcomes.values())


def question_coverage_errors(question, verdict, accepted, bundle):
    requirements = coverage_requirements(question)
    if not requirements:
        return []
    findings = {f.id: f for f in accepted if question.id in f.question_ids}
    rows = bundle.comparison.get("sensitivity", {}).get("rows", [])
    errors = []
    for requirement in requirements:
        rid = requirement["id"]
        entries = [c for c in verdict.coverage if c.requirement_id == rid] if verdict else []
        valid = False
        located_quotes = []
        for entry in entries:
            finding = findings.get(entry.finding_id)
            if not finding or entry.quote not in finding.text:
                continue
            located_quotes.append(entry.quote)
            if rid.startswith("product:"):
                token = rid.removeprefix("product:")
                valid = mentions(entry.quote, token) and any(
                    mentions(e.quote, token) for e in finding.evidence
                )
            if valid:
                break
        if not rid.startswith("product:"):
            valid = has_scenario_comparison("\n".join(located_quotes), rid, rows)
        if not valid:
            errors.append(f"子要求未获得可定位的正文依据：{requirement['description']}")
    return errors
