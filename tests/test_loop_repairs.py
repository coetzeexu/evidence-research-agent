from types import SimpleNamespace

import pytest
from research_app.budget import ExecutionBudget
from research_app.research_contract import (
    ClaimVerdict,
    GapResolution,
    LocatedNumericAssertion,
    MeaningCheck,
    MeaningReview,
    NarrativeDraft,
    NarrativePatch,
    NarrativeReview,
    NumericAssertion,
    NumericClaimReview,
    NumericReview,
    QuestionVerdict,
    ResearchFinding,
    ResearchGap,
    ResearchQuestion,
    apply_narrative_patch,
)
from research_app.research_logic import repair_numeric_transcription, verify_relationships
from research_app.research_metrics import metric_catalog
from research_app.research_text import NarrativeService, gap_id, unresolved_gaps
from research_app.storage import Store


def draft_finding():
    return ResearchFinding(
        id="f",
        question_ids=["q"],
        kind="analysis",
        title="实际回测",
        text="组合收益为 {{execution.portfolio.total_return}}。",
        limitations="有限历史样本不能代表未来表现。",
    )


def runtime_for(tmp_path, structured):
    store = Store(tmp_path)
    rid = store.create("loop repair", export_reports=False)
    return SimpleNamespace(
        store=store,
        run_id=rid,
        root=store.run_dir(rid),
        structured=structured,
        budget=ExecutionBudget(store, rid),
        texts={},
    )


@pytest.mark.parametrize("verdict", ["supported", "unsupported"])
async def test_correct_quote_is_repaired_without_changing_draft_or_verdict(bundle, tmp_path, verdict):
    metrics = metric_catalog(bundle)
    mid = "execution.portfolio.total_return"
    # Use observed sign, so this fixture tests exact quote failure, not model arithmetic.
    relation = "positive" if metrics[mid].value > 0 else "negative"
    phrase = "为正" if relation == "positive" else "为负"
    finding = draft_finding().model_copy(update={"text": f"组合收益 {{{{{mid}}}}}，收益{phrase}。"})
    draft = NarrativeDraft(findings=[finding])
    review = NarrativeReview(
        claims=[
            ClaimVerdict(
                finding_id="f",
                verdict=verdict,
                reason="原始来源判断必须保留",
                numeric_assertions=[
                    NumericAssertion(quote="模型改写后的比较句", relation=relation, metric_ids=[mid])
                ],
            )
        ],
        questions=[],
    )
    original = draft.model_dump()
    calls = []

    async def structured(name, schema, context, **kwargs):
        calls.append(name)
        assert context["program_checks"][0]["quote_found"] is False
        assert context["program_checks"][0]["relationship_true"] is True
        return NumericReview(
            claims=[
                NumericClaimReview(
                    finding_id="f",
                    numeric_assertions=[
                        LocatedNumericAssertion(span_id="f:text:1", relation=relation, metric_ids=[mid])
                    ],
                )
            ]
        )

    corrected, audit = await repair_numeric_transcription(
        runtime_for(tmp_path, structured), draft, review, metrics, SimpleNamespace(remaining=100)
    )
    assert not verify_relationships(draft, corrected, metrics)[0]
    assert corrected.claims[0].verdict == verdict
    assert draft.model_dump() == original and calls == ["numeric-review"]
    assert audit[0]["before"] == review.model_dump()


async def test_numeric_retry_failure_keeps_original_rejection(bundle, tmp_path):
    finding = draft_finding()
    draft = NarrativeDraft(findings=[finding])
    review = NarrativeReview(
        claims=[
            ClaimVerdict(
                finding_id="f",
                verdict="supported",
                reason="原始判断",
                numeric_assertions=[
                    NumericAssertion(quote="不存在的比较句", relation="positive", metric_ids=["missing"])
                ],
            )
        ],
        questions=[],
    )

    async def structured(*args, **kwargs):
        raise TimeoutError()

    result, audit = await repair_numeric_transcription(
        runtime_for(tmp_path, structured),
        draft,
        review,
        metric_catalog(bundle),
        SimpleNamespace(remaining=100),
    )
    assert result is review and verify_relationships(draft, result, metric_catalog(bundle))[0]
    assert audit[0]["error_type"] == "TimeoutError"


async def test_declared_missing_fact_survives_patches_and_cannot_be_complete(bundle, tmp_path):
    bundle.quality = {"passed": True}
    gap = ResearchGap(question_id="q", reason="论文公开日期未取得证据")
    finding = draft_finding()
    finding.limitations += "论文公开日期未取得证据。"

    async def structured(name, schema, context, **kwargs):
        if name == "synthesis":
            return NarrativeDraft(findings=[finding], gaps=[gap])
        if name == "text-repair":
            return NarrativePatch()
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id=f["id"], inference_audit="正文只是披露已知结果和证据缺口", violations=[]
                    )
                    for f in context["draft"]["findings"]
                ]
            )
        assert context["open_gaps"][0]["id"] == gap_id(gap)
        return NarrativeReview(
            claims=[
                ClaimVerdict(finding_id=f["id"], verdict="supported", reason="有限表述")
                for f in context["draft"]["findings"]
            ],
            questions=[
                QuestionVerdict(question_id="q", answered=True, reason="模拟旧核验器：披露缺口也算回答")
            ],
        )

    runtime = runtime_for(tmp_path, structured)
    q = ResearchQuestion(id="q", question="要求论文公开日期", acceptance="原文核实日期", kind="event")
    result = await NarrativeService(runtime).compose(bundle, [q])
    assert result.status == "partial" and "论文公开日期" in result.gaps[0].reason
    assert result.questions[0].status == "insufficient"
    assert all(r["open_gaps"] for r in result.reviews)
    # Restoring an exhausted task must not silently clear the gap.
    resumed = await NarrativeService(runtime).compose(bundle, [q])
    assert resumed.status == "partial" and resumed.gaps == result.gaps


def test_gap_closure_requires_located_accepted_answer():
    gap = ResearchGap(question_id="q", reason="缺少具体日期")
    f = draft_finding().model_copy(update={"text": "论文原文明确记载发布日期为 2025-01-22。"})
    draft = apply_narrative_patch([f], [], NarrativePatch(), [gap])
    verdict = QuestionVerdict(question_id="q", answered=True, reason="日期已回答")
    review = NarrativeReview(claims=[], questions=[verdict])
    assert unresolved_gaps(draft, review, [f]) == [gap]
    verdict.resolved_gaps = [
        GapResolution(
            gap_id=gap_id(gap), finding_id="f", quote=f.text, reason="已核验结论补齐了原本缺失的发布日期"
        )
    ]
    assert not unresolved_gaps(draft, review, [f])
    assert unresolved_gaps(draft, review, []) == [gap]
    verdict.resolved_gaps[0].quote = "一个无法在发布正文中定位到的日期证据"
    assert unresolved_gaps(draft, review, [f]) == [gap]
