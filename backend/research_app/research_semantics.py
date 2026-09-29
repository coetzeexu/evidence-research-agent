"""Require an explicit, locatable inference audit independently of numeric review."""


def verify_meaning(draft, review):
    errors = {}
    for finding in draft.findings:
        checks = [c for c in review.checks if c.finding_id == finding.id]
        if len(checks) != 1:
            errors[finding.id] = ["结论含义尚未获得唯一的独立核验"]
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
