"""Require an explicit, locatable inference audit independently of numeric review."""

import re


def descriptive_inference_errors(finding):
    """This engine estimates descriptive CPI associations, not a causal mechanism."""
    if "inflation" not in finding.question_ids:
        return []
    errors = []
    for field in ("title", "text", "counterevidence", "limitations", "changes_if"):
        for sentence in re.split(r"[。；;\n]", getattr(finding, field)):
            for match in re.finditer(
                r"机制(?:不成立|成立|不存在)|无稳定抗通胀机制|不存在稳定.{0,5}机制", sentence
            ):
                prefix = sentence[: match.start()]
                if re.search(r"不能|无法|不足以|不支持|未能|尚未|是否|若|如果|假设", prefix):
                    continue
                errors.append(f"{field} 将描述性统计外推为机制判定：{match[0]}；只能表述本样本的关联与局限")
    return errors


def verify_meaning(draft, review):
    errors = {}
    for finding in draft.findings:
        if issues := descriptive_inference_errors(finding):
            errors[finding.id] = issues
        checks = [c for c in review.checks if c.finding_id == finding.id]
        if len(checks) != 1:
            errors.setdefault(finding.id, []).append("结论含义尚未获得唯一的独立核验")
            continue
        full_text = "\n".join(
            getattr(finding, field)
            for field in ["title", "text", "counterevidence", "limitations", "changes_if"]
        )
        for violation in checks[0].violations:
            if violation.quote not in full_text:
                issue = f"语义核验的缺陷位置无法定位：{violation.quote}；需要重新核对"
            else:
                issue = f"推断/事实缺陷：{violation.quote}；{violation.reason}；修复方向 {violation.repair}"
            errors.setdefault(finding.id, []).append(issue)
    return errors
