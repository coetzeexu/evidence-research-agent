"""Execute the reviewer’s transcription of numerical claims, independently of its verdict."""

import math
import re

from .research_contract import NumericAssertion, NumericReview


def relationship(relation, values):
    if not values:
        return False
    if relation in {"abs_gt", "abs_lt", "abs_increasing", "abs_decreasing"}:
        return relationship(relation.removeprefix("abs_"), [abs(value) for value in values])
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
            check["quote_found"] = assertion.quote in full_text
            check["relationship_true"] = len(values) == len(assertion.metric_ids) and relationship(
                assertion.relation, values
            )
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


def numeric_spans(draft):
    spans = {}
    for finding in draft.findings:
        for field in ("title", "text", "counterevidence", "limitations", "changes_if"):
            for index, match in enumerate(re.finditer(r"[^。；;，,\n]+", getattr(finding, field))):
                text = match[0].strip()
                if text:
                    spans[f"{finding.id}:{field}:{index}"] = {"finding_id": finding.id, "text": text}
    return spans


async def repair_numeric_transcription(runtime, draft, review, metrics, budget):
    """Repair the reviewer, not the immutable prose. Never change semantic verdicts."""
    errors, checks = verify_relationships(draft, review, metrics)
    if not errors or budget.remaining <= 2:
        return review, []
    affected = set(errors)
    spans = numeric_spans(draft)
    audit = {"before": review.model_dump(), "errors": errors, "checks": checks}
    runtime.store.emit(runtime.run_id, "step", "修正核验器数值转录", phase="text_review")
    try:
        corrected = await runtime.structured(
            "numeric-review",
            NumericReview,
            {
                "draft": {"findings": [f.model_dump() for f in draft.findings if f.id in affected]},
                "metric_catalog": [m.model_dump() for m in metrics.values()],
                "previous_claims": [v.model_dump() for v in review.claims if v.finding_id in affected],
                "program_errors": errors,
                "program_checks": checks,
                "spans": [
                    {"id": sid, **span} for sid, span in spans.items() if span["finding_id"] in affected
                ],
            },
            budget=budget,
            limit=1,
        )
        ids = [v.finding_id for v in corrected.claims]
        if set(ids) != affected or len(ids) != len(set(ids)):
            raise ValueError("数值转录必须恰好覆盖待修复条目")
        replacements = {}
        for claim in corrected.claims:
            replacements[claim.finding_id] = []
            for assertion in claim.numeric_assertions:
                span = spans.get(assertion.span_id)
                if not span or span["finding_id"] != claim.finding_id:
                    raise ValueError("数值转录引用未知片段或其他结论")
                replacements[claim.finding_id].append(
                    NumericAssertion(
                        quote=span["text"], relation=assertion.relation, metric_ids=assertion.metric_ids
                    )
                )
        result = review.model_copy(deep=True)
        for verdict in result.claims:
            if verdict.finding_id in replacements:
                verdict.numeric_assertions = replacements[verdict.finding_id]
        audit["after"] = corrected.model_dump()
        audit["remaining_errors"] = verify_relationships(draft, result, metrics)[0]
        return result, [audit]
    except Exception as exc:
        # Timeout/schema/transport failures cannot turn a failed check into a pass.
        audit["error_type"] = type(exc).__name__
        return review, [audit]
