"""Execute the reviewer’s transcription of numerical claims, independently of its verdict."""

import math
import re


def relationship(relation, values):
    if not values:
        return False
    if relation in {"same_sign", "opposite_sign"}:
        return len(values) == 2 and (
            values[0] * values[1] > 0 if relation == "same_sign" else values[0] * values[1] < 0
        )
    if relation in {"positive", "negative", "nonnegative", "nonpositive"}:
        test = {
            "positive": lambda x: x > 0,
            "negative": lambda x: x < 0,
            "nonnegative": lambda x: x >= 0,
            "nonpositive": lambda x: x <= 0,
        }[relation]
        return all(test(x) for x in values)
    if relation in {"between", "not_between"}:
        if len(values) != 3:
            return False
        inside = min(values[1:]) <= values[0] <= max(values[1:])
        return inside if relation == "between" else not inside
    if len(values) < 2:
        return False
    if relation in {"increasing", "decreasing"}:
        return all((a < b if relation == "increasing" else a > b) for a, b in zip(values, values[1:]))
    tests = {
        "gt": lambda a, b: a > b,
        "ge": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "le": lambda a, b: a <= b,
        "eq": lambda a, b: math.isclose(a, b, abs_tol=1e-10, rel_tol=1e-8),
    }
    return relation in tests and all(tests[relation](values[0], v) for v in values[1:])


def verify_relationships(draft, review, metrics):
    findings = {f.id: f for f in draft.findings}
    errors, checks = {}, []
    for verdict in review.claims:
        finding = findings.get(verdict.finding_id)
        if finding is None:
            continue
        full_text = "\n".join(
            [finding.title, finding.text, finding.counterevidence, finding.limitations, finding.changes_if]
        )
        for assertion in verdict.numeric_assertions:
            values = [metrics[mid].value for mid in assertion.metric_ids if mid in metrics]
            units = {metrics[mid].unit for mid in assertion.metric_ids if mid in metrics}
            passed = (
                assertion.quote in full_text
                and len(values) == len(assertion.metric_ids)
                and len(set(assertion.metric_ids)) == len(assertion.metric_ids)
                and (
                    len(units) == 1
                    or assertion.relation in {"positive", "negative", "nonnegative", "nonpositive"}
                )
                and relationship(assertion.relation, values)
            )
            check = {"finding_id": finding.id, **assertion.model_dump(), "values": values, "passed": passed}
            checks.append(check)
            if not passed:
                errors.setdefault(finding.id, []).append(
                    f"数值关系未成立或绑定错误：{assertion.quote}；{assertion.relation} {assertion.metric_ids} = {values}"
                )
        # Important ordinal/sign claims must be transcribed, rather than just receiving a prose pass.
        for sentence in re.split(r"[。；;\n]", full_text):
            if re.search(r"若|如果|可能|假设", sentence):
                continue
            for match in re.finditer(
                r"高于|低于|少于|多于|居中|均为正|均为负|同为正|同为负|同向为正|同向为负|双双上涨|双双下跌|方向相反|同涨同跌|最高|最低",
                sentence,
            ):
                if re.search(r"(?:可信度|置信度|证据强度|证据评级)[^，、]{0,5}$", sentence[: match.start()]):
                    continue
                if not any(match[0] in a.quote and a.quote in full_text for a in verdict.numeric_assertions):
                    errors.setdefault(finding.id, []).append(
                        f"数值关系尚未转成可执行断言：{match[0]}；应按收益/风险分别核对"
                    )
    return errors, checks
