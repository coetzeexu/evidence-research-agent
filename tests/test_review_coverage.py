from pathlib import Path
from types import SimpleNamespace

import pytest
from research_app.budget import ExecutionBudget
from research_app.domain import ResearchBundle
from research_app.research_contract import (
    ClaimVerdict,
    EvidenceQuote,
    MeaningCheck,
    MeaningReview,
    NarrativeDraft,
    NarrativePatch,
    NarrativeReview,
    QuestionCoverageReview,
    QuestionVerdict,
    RequirementCoverage,
    ResearchFinding,
    ResearchQuestion,
)
from research_app.research_coverage import (
    coverage_requirements,
    has_scenario_comparison,
    question_coverage_errors,
)
from research_app.research_text import NarrativeService
from research_app.storage import Store


def product_question():
    return ResearchQuestion(
        id="product",
        kind="event",
        question="核实型号发布",
        acceptance="分别核实",
        required_event="Blackwell（B100/B200）平台发布",
    )


def product_finding():
    return ResearchFinding(
        id="f",
        question_ids=["product"],
        kind="fact",
        title="发布",
        text="公告介绍了 B100 和 B200 的发布事实。",
        evidence=[EvidenceQuote(source_id="source", quote="The launch includes B100 and B200.")],
        limitations="仅核实公告内容。",
    )


def verdict_for(question, findings):
    # Deliberately optimistic reviewer: claims every accepted paragraph answers
    # every requirement, so the program must detect absent underlying coverage.
    return QuestionVerdict(
        question_id=question.id,
        answered=True,
        reason="模拟乐观判定",
        coverage=[
            RequirementCoverage(requirement_id=r["id"], finding_id=f.id, quote=f.text)
            for r in coverage_requirements(question)
            for f in findings
        ],
    )


@pytest.mark.parametrize(
    "fault", ["none", "missing_product", "wrong_quote", "wrong_question", "missing_evidence", "rejected"]
)
def test_product_coverage_requires_accepted_located_answer_and_source(bundle, fault):
    q, f = product_question(), product_finding()
    if fault == "missing_product":
        f.text = f.text.replace("B100", "GB100")
    if fault == "wrong_question":
        f.question_ids = ["other"]
    if fault == "missing_evidence":
        f.evidence = []
    verdict = verdict_for(q, [f])
    if fault == "wrong_quote":
        for c in verdict.coverage:
            c.quote = "编造的 B100 和 B200 发布事实"
    errors = question_coverage_errors(q, verdict, [] if fault == "rejected" else [f], bundle)
    assert bool(errors) == (fault != "none")


@pytest.mark.parametrize(
    "quote,dimension,expected",
    [
        ("{{sensitivity.1.cagr}} 对比 {{execution.portfolio.cagr}}", "frequency", True),
        ("{{sensitivity.1.cagr}} 对比 {{sensitivity.2.cagr}}", "frequency", True),
        ("{{sensitivity.1.cagr}} 对比 {{sensitivity.1.cagr}}", "frequency", False),
        ("{{sensitivity.1.rebalance_months}} 对比 {{sensitivity.2.rebalance_months}}", "frequency", False),
        ("{{sensitivity.0.cagr}} 对比 {{execution.portfolio.cagr}}", "frequency", False),
        ("{{sensitivity.3.cagr}} 对比 {{sensitivity.4.cagr}}", "period", True),
        ("{{sensitivity.3.cagr}} 对比 {{execution.portfolio.cagr}}", "period", False),
        ("{{sensitivity.1.cagr}} 对比 {{sensitivity.2.volatility}}", "frequency", False),
    ],
)
def test_sensitivity_requires_distinct_scenarios_and_same_outcome(quote, dimension, expected):
    rows = [{"dimension": d} for d in ["baseline", "frequency", "frequency", "period", "period"]]
    assert has_scenario_comparison(quote, dimension, rows) is expected


@pytest.mark.parametrize(
    "folder,pattern,qid,missing",
    [
        ("P0FinalGold20260929", "gold-bitcoin-*.bundle.json", "sensitivity", "再平衡频率"),
        ("P0FinalNVDA20260929", "nvda-*.bundle.json", "required-2", "B100"),
    ],
)
def test_real_p0_omissions_fail_even_with_optimistic_coverage(folder, pattern, qid, missing):
    root = Path(__file__).resolve().parents[1] / "evals/text-research" / folder
    bundle = ResearchBundle.model_validate_json(next(root.glob(pattern)).read_text())
    q = next(q for q in bundle.research.questions if q.id == qid)
    findings = bundle.research.findings
    errors = question_coverage_errors(q, verdict_for(q, findings), findings, bundle)
    assert any(missing in error for error in errors)


@pytest.mark.parametrize("covered", [True, False])
async def test_coverage_gate_and_resume(bundle, tmp_path, covered):
    store = Store(tmp_path)
    rid = store.create("coverage")
    q = product_question()
    bundle.quality = {"passed": True}
    bundle.events[0].satisfies = [q.required_event]
    # This accepted calculation does not answer either required product fact.
    f = product_finding()
    f.evidence[0].source_id = "src-test"
    if not covered:
        f.text = "组合收益为 {{execution.portfolio.total_return}}。"
        f.evidence = []

    async def structured(name, schema, context, **kwargs):
        if name == "synthesis":
            assert context["verification_version"] == "1.5"
            return NarrativeDraft(findings=[f])
        if name == "text-repair":
            assert any("B100" in g for q in context["repair"]["unanswered_questions"] for g in q["gaps"])
            return NarrativePatch()
        if name == "text-reviewer":
            return NarrativeReview(
                claims=[
                    ClaimVerdict(finding_id=r["id"], verdict="supported", reason="数字正确")
                    for r in context["draft"]["findings"]
                ],
                questions=[],
            )
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id=r["id"], inference_audit="有限历史数值观察没有推断跳跃", violations=[]
                    )
                    for r in context["draft"]["findings"]
                ]
            )
        assert name == "question-review"
        return QuestionCoverageReview(questions=[verdict_for(q, [f])])

    runtime = SimpleNamespace(
        store=store,
        root=store.run_dir(rid),
        run_id=rid,
        budget=ExecutionBudget(store, rid),
        texts={"src-test": "The launch includes B100 and B200."},
        structured=structured,
    )
    service = NarrativeService(runtime)
    for _ in range(2):
        result = await service.compose(bundle, [q])
        assert result.status == ("complete" if covered else "partial")
        assert result.questions[0].status == ("answered" if covered else "insufficient")
        if not covered:
            assert "B100" in result.gaps[0].reason
            assert result.reviews[-1]["coverage_errors"]["product"]
        assert result.findings[0].text == f.text


def test_sensitivity_can_be_answered_across_multiple_accepted_excerpts(bundle):
    q = ResearchQuestion(id="sensitivity", kind="sensitivity", question="敏感性", acceptance="四维比较")
    bundle.comparison["sensitivity"] = {
        "rows": [{"dimension": d} for d in ["cost", "weights", "frequency", "period", "period"]]
    }
    base = product_finding().model_copy(
        update={
            "id": "base",
            "question_ids": [q.id],
            "text": "基线年化为 {{execution.portfolio.cagr}}。",
        }
    )
    findings = [base] + [
        base.model_copy(update={"id": str(i), "text": "{{sensitivity." + str(i) + ".cagr}}"})
        for i in range(5)
    ]
    assert not question_coverage_errors(q, verdict_for(q, findings), findings, bundle)
