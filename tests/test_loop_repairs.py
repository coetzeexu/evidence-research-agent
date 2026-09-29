import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from research_app.budget import ExecutionBudget
from research_app.research_contract import (
    ClaimVerdict,
    GapResolution,
    LocatedNumericAssertion,
    MeaningCheck,
    MeaningReview,
    MeaningViolation,
    NarrativeDraft,
    NarrativePatch,
    NarrativeReview,
    NumericAssertion,
    NumericClaimReview,
    NumericReview,
    QuestionCoverageReview,
    QuestionVerdict,
    ResearchFinding,
    ResearchGap,
    ResearchQuestion,
    TextEdit,
    apply_narrative_patch,
)
from research_app.research_logic import relationship, repair_numeric_transcription, verify_relationships
from research_app.research_metrics import metric_catalog
from research_app.research_text import (
    NarrativeService,
    gap_id,
    normalize_metric_tokens,
    research_questions,
    unresolved_gaps,
    validate_draft,
)
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


@pytest.mark.parametrize("noop_first", [True, False])
def test_exact_noop_patch_keeps_valid_sibling_edit_and_previous_gap(noop_first):
    retained = draft_finding().model_copy(update={"id": "kept"})
    rejected = draft_finding().model_copy(update={"text": "组合收益保证未来盈利。"})
    originals = [f.model_dump() for f in [retained, rejected]]
    noop = TextEdit(finding_id="f", field="title", old=rejected.title, new=rejected.title)
    correction = TextEdit(finding_id="f", field="text", old="保证未来盈利", new="不能保证未来盈利")
    gap = ResearchGap(question_id="q", reason="用户要求的论文公开日期仍未核实")

    draft = apply_narrative_patch(
        [retained],
        [rejected],
        NarrativePatch(edits=[noop, correction] if noop_first else [correction, noop]),
        [gap],
    )

    assert [f.id for f in draft.findings] == ["kept", "f"]
    assert draft.findings[0].model_dump() == originals[0]
    assert draft.findings[1].title == rejected.title
    assert draft.findings[1].text == "组合收益不能保证未来盈利。"
    assert draft.gaps == [gap]
    assert [f.model_dump() for f in [retained, rejected]] == originals


@pytest.mark.parametrize(
    "target,old,new,error",
    [
        ("f", "不存在的原文", "不存在的原文", "替换必须匹配失败结论原文"),
        ("kept", "实际回测", "实际回测", "修复不能修改已核验结论或未知 ID"),
        ("kept", "实际回测", "改写标题", "修复不能修改已核验结论或未知 ID"),
    ],
)
def test_noop_patch_still_requires_exact_rejected_target(target, old, new, error):
    retained = draft_finding().model_copy(update={"id": "kept"})
    rejected = draft_finding()
    originals = [f.model_dump() for f in [retained, rejected]]
    patch = NarrativePatch(edits=[TextEdit(finding_id=target, field="title", old=old, new=new)])
    with pytest.raises(ValueError, match=error):
        apply_narrative_patch([retained], [rejected], patch)
    assert [f.model_dump() for f in [retained, rejected]] == originals


def test_custom_questions_deduplicate_exact_request_quote_without_merging_distinct_facts(spec):
    model_quote = "核实 DeepSeek 模型发布日期"
    paper_quote = "核实 DeepSeek 论文公开日期"
    request = f"{model_quote}；{paper_quote}。"
    extra = [
        ResearchQuestion(
            id=qid,
            question=title,
            acceptance="模型自行增加的高等级来源要求",
            kind="event",
            request_quote=quote,
            status="answered",
            finding_ids=["old-finding"],
            gaps=["旧问题缺口"],
        ).model_dump()
        for qid, title, quote in [
            ("one", "模型发布", model_quote),
            ("two", "发布事件的另一种表述", model_quote),
            ("three", "论文公开", paper_quote),
        ]
    ]
    original = deepcopy(extra)
    questions = research_questions(spec, extra, request)
    custom = [q for q in questions if q.id.startswith("custom-")]

    assert [q.id for q in custom] == ["custom-1", "custom-2"]
    assert [q.request_quote for q in custom] == [model_quote, paper_quote]
    assert [q.question for q in custom] == [model_quote, paper_quote]
    assert all(q.acceptance.endswith(q.request_quote) for q in custom)
    assert all("高等级来源" not in q.acceptance for q in custom)
    assert all(q.required and q.priority == 1 for q in custom)
    assert all(q.status == "pending" and not q.finding_ids and not q.gaps for q in custom)
    assert extra == original
    assert [q.id for q in questions if not q.id.startswith("custom-")] == [
        q.id for q in research_questions(spec)
    ]


@pytest.mark.parametrize("second_response_valid", [True, False])
async def test_question_coverage_has_two_sdk_attempts_and_empty_objects_cannot_publish(
    bundle, tmp_path, second_response_valid
):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from research_app.agents import AgentRuntime, prompt

    bundle.quality = {"passed": True}
    question = ResearchQuestion(id="q", question="比较收益", acceptance="确定性数值", kind="market")
    requests = []
    phases = []

    class CoverageModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            requests.append(messages)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    valid = {"questions": [{"question_id": "q", "answered": True, "reason": "已核验收益回答明确要求"}]}
    model = CoverageModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "QuestionCoverageReview", "id": "empty-first", "args": {}}],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "QuestionCoverageReview",
                        "id": "second",
                        "args": valid if second_response_valid else {},
                    }
                ],
            ),
        ]
    )

    async def structured(name, schema, context, **kwargs):
        phases.append(name)
        if name == "synthesis":
            return NarrativeDraft(findings=[draft_finding()])
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id="f", inference_audit="确定性收益陈述未添加额外因果推断", violations=[]
                    )
                ]
            )
        if name == "text-reviewer":
            return NarrativeReview(
                claims=[ClaimVerdict(finding_id="f", verdict="supported", reason="收益引用正确")],
                questions=[],
            )
        assert name == "question-review" and schema is QuestionCoverageReview
        assert kwargs["limit"] == 2
        assert [f["id"] for f in context["accepted_findings"]] == ["f"]
        return await AgentRuntime.structured(runtime, name, schema, context, **kwargs)

    runtime = runtime_for(tmp_path, structured)
    runtime.model = model
    runtime.prompts = {"question-review": prompt("question-review")}
    result = await NarrativeService(runtime).compose(bundle, [question])

    assert len(requests) == 2
    assert phases.count("question-review") == 1 and "text-repair" not in phases
    state = json.loads((runtime.root / "research-text-attempts.json").read_text())
    assert state["attempts"] == 1
    diagnostics = [json.loads(path.read_text()) for path in runtime.root.glob("structure-*.json")]
    assert len(diagnostics) == 2
    assert sum(bool(row["validation_errors"]) for row in diagnostics) == (1 if second_response_valid else 2)
    if second_response_valid:
        assert result.status == "complete" and [f.id for f in result.findings] == ["f"]
        assert result.questions[0].status == "answered"
    else:
        assert result.status == "failed" and not result.findings and not result.text
        assert result.reviews[-1]["error_type"] == "ModelCallLimitExceededError"


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
        if name == "question-review":
            assert schema is QuestionCoverageReview
            assert context["accepted_findings"][0]["id"] == finding.id
            # Even an optimistic coverage answer must not erase a declared missing fact.
            return QuestionCoverageReview(
                questions=[
                    QuestionVerdict(question_id="q", answered=True, reason="模拟覆盖误判：承认缺口即回答")
                ]
            )
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


@pytest.mark.parametrize("field", ["title", "text", "counterevidence", "limitations", "changes_if"])
def test_metric_prefix_normalization_only_uses_existing_exact_id(bundle, field):
    mid = "execution.portfolio.total_return"
    draft = NarrativeDraft(findings=[draft_finding()])
    setattr(draft.findings[0], field, "收益为 {{metric_id:" + mid + "}}。")
    repairs = normalize_metric_tokens(draft, metric_catalog(bundle))
    assert getattr(draft.findings[0], field) == "收益为 {{" + mid + "}}。"
    assert repairs == [{"finding_id": "f", "field": field, "from": "metric_id:" + mid, "to": mid}]
    assert normalize_metric_tokens(draft, metric_catalog(bundle)) == []


@pytest.mark.parametrize(
    "token",
    [
        "metric_id:execution.portfolio.missing",
        "metric_id:execution.portfolio.total_Return",
        "metric_id:metric_id:execution.portfolio.total_return",
        "metric-id:execution.portfolio.total_return",
        "metric_id: execution.portfolio.total_return",
    ],
)
def test_unknown_or_approximate_metric_id_is_not_guessed(bundle, token):
    text = "收益为 {{" + token + "}}。"
    draft = NarrativeDraft(findings=[draft_finding().model_copy(update={"text": text})])
    metrics = metric_catalog(bundle)
    assert normalize_metric_tokens(draft, metrics) == []
    assert draft.findings[0].text == text
    q = ResearchQuestion(id="q", question="比较收益", acceptance="确定性数值", kind="market")
    errors, _ = validate_draft(draft, bundle, [q], {}, metrics)
    assert "f" in errors
    assert any("数值引用不存在" in error or "占位符格式错误" in error for error in errors["f"])


@pytest.mark.parametrize(
    "relation, values, expected",
    [
        ("abs_gt", [-0.40, -0.20], True),
        ("abs_gt", [-0.40, 0.20], True),
        ("abs_gt", [0.40, -0.20, 0.30], True),
        ("abs_gt", [-0.20, -0.40], False),
        ("abs_gt", [0.40, -0.40], False),
        ("abs_gt", [0.40, 0.20, -0.50], False),
        ("abs_lt", [-0.20, -0.40], True),
        ("abs_lt", [0.20, -0.40], True),
        ("abs_lt", [-0.20, -0.40, 0.30], True),
        ("abs_lt", [-0.40, -0.20], False),
        ("abs_lt", [0.40, -0.40], False),
        ("abs_lt", [0.20, 0.40, -0.10], False),
        ("abs_increasing", [-0.20, -0.30, -0.40], True),
        ("abs_increasing", [0.20, -0.30, 0.40], True),
        ("abs_increasing", [-0.40, -0.30, -0.20], False),
        ("abs_increasing", [0.20, -0.40, 0.30], False),
        ("abs_increasing", [0.20, -0.20], False),
        ("abs_decreasing", [-0.40, -0.30, -0.20], True),
        ("abs_decreasing", [0.40, -0.30, 0.20], True),
        ("abs_decreasing", [-0.20, -0.30, -0.40], False),
        ("abs_decreasing", [0.40, -0.20, 0.30], False),
        ("abs_decreasing", [0.20, -0.20], False),
    ],
)
def test_magnitude_relations_compare_absolute_values_in_original_order(relation, values, expected):
    assert relationship(relation, values) is expected


@pytest.mark.parametrize("relation", ["abs_gt", "abs_lt", "abs_increasing", "abs_decreasing"])
@pytest.mark.parametrize("values", [[], [-0.20]])
def test_magnitude_comparisons_require_multiple_values(relation, values):
    assert relationship(relation, values) is False


@pytest.mark.parametrize("values, expected", [([-0.40, -0.20], True), ([-0.20, -0.40], False)])
def test_drawdown_magnitude_assertion_is_executed_after_schema_validation(bundle, values, expected):
    mids = ["execution.portfolio.max_drawdown", "execution.GLD.max_drawdown"]
    metrics = metric_catalog(bundle)
    for mid, value in zip(mids, values):
        metrics[mid] = metrics[mid].model_copy(update={"value": value})
    draft = NarrativeDraft(findings=[draft_finding().model_copy(update={"text": "组合回撤幅度高于黄金。"})])
    review = NarrativeReview(
        claims=[
            ClaimVerdict(
                finding_id="f",
                verdict="supported",
                reason="不能用核验者的通过判定替代幅度计算",
                numeric_assertions=[
                    NumericAssertion(quote="组合回撤幅度高于黄金", relation="abs_gt", metric_ids=mids)
                ],
            )
        ],
        questions=[],
    )
    errors, checks = verify_relationships(draft, review, metrics)
    assert checks[0]["passed"] is expected
    assert ("f" in errors) is not expected


async def test_question_coverage_uses_only_accepted_findings_and_its_own_verdict(bundle, tmp_path):
    bundle.quality = {"passed": True}
    q = ResearchQuestion(id="q", question="比较收益", acceptance="确定性数值", kind="market")
    finding = draft_finding().model_copy(
        update={"text": "组合收益为 {{metric_id:execution.portfolio.total_return}}。"}
    )
    calls = []

    async def structured(name, schema, context, **kwargs):
        calls.append(name)
        if name == "synthesis":
            return NarrativeDraft(findings=[finding])
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id="f", inference_audit="只展示同口径回测结果，未增加推断", violations=[]
                    )
                ]
            )
        if name == "text-reviewer":
            return NarrativeReview(
                claims=[ClaimVerdict(finding_id="f", verdict="supported", reason="指标引用正确")],
                questions=[
                    QuestionVerdict(question_id="q", answered=False, reason="旧阶段误将未要求的回归列为缺口")
                ],
            )
        assert name == "question-review" and schema is QuestionCoverageReview
        assert set(context) == {
            "request",
            "questions",
            "accepted_findings",
            "open_gaps",
            "available_metric_ids",
        }
        assert context["request"] == "比较收益"
        assert context["questions"][0]["acceptance"] == "确定性数值"
        assert len(context["accepted_findings"]) == 1
        assert context["accepted_findings"][0]["text"] == "组合收益为 {{execution.portfolio.total_return}}。"
        assert "execution.portfolio.total_return" in context["available_metric_ids"]
        assert context["open_gaps"] == []
        return QuestionCoverageReview(
            questions=[QuestionVerdict(question_id="q", answered=True, reason="已批准结论回答请求的收益")]
        )

    result = await NarrativeService(runtime_for(tmp_path, structured)).compose(
        bundle, [q], request="比较收益"
    )
    assert result.status == "complete" and len(result.findings) == 1
    assert "{{" not in result.text and "metric_id:" not in result.text
    assert calls.count("question-review") == 1 and "text-repair" not in calls
    audit = result.reviews[0]
    assert audit["source_question_review"][0]["answered"] is False
    assert audit["review"]["questions"][0]["answered"] is True
    assert audit["review"]["claims"][0]["reason"] == "指标引用正确"
    assert audit["metric_token_repairs"][0]["to"] == "execution.portfolio.total_return"


@pytest.mark.parametrize("rejection", ["unsupported", "missing_claim", "meaning_violation"])
async def test_positive_question_coverage_cannot_approve_rejected_claims(bundle, tmp_path, rejection):
    bundle.quality = {"passed": True}
    q = ResearchQuestion(id="q", question="比较收益", acceptance="确定性数值", kind="market")
    coverage_calls = []

    async def structured(name, schema, context, **kwargs):
        if name == "synthesis":
            return NarrativeDraft(findings=[draft_finding()])
        if name == "text-repair":
            return NarrativePatch()
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id="f",
                        inference_audit="测试结论证据支持边界，不以覆盖声明替代核验",
                        violations=[MeaningViolation(quote="组合收益", reason="测试保留实质证据缺陷")]
                        if rejection == "meaning_violation"
                        else [],
                    )
                ]
            )
        if name == "text-reviewer":
            return NarrativeReview(
                claims=[]
                if rejection == "missing_claim"
                else [
                    ClaimVerdict(
                        finding_id="f",
                        verdict="unsupported" if rejection == "unsupported" else "supported",
                        reason="保持原事实判断",
                    )
                ],
                questions=[QuestionVerdict(question_id="q", answered=True, reason="不能覆盖事实门禁")],
            )
        assert name == "question-review"
        assert context["accepted_findings"] == []
        coverage_calls.append(context)
        return QuestionCoverageReview(
            questions=[QuestionVerdict(question_id="q", answered=True, reason="模拟覆盖核验的乐观误判")]
        )

    result = await NarrativeService(runtime_for(tmp_path, structured)).compose(bundle, [q])
    assert len(coverage_calls) == 3
    assert result.status == "failed" and not result.text and not result.findings
    assert all(not review["accepted_ids"] for review in result.reviews)
    if rejection == "unsupported":
        assert all(review["review"]["claims"][0]["verdict"] == "unsupported" for review in result.reviews)


@pytest.mark.parametrize("core_fact_rejected", [False, True])
async def test_rejected_optional_finding_does_not_override_verified_question_coverage(
    bundle, tmp_path, core_fact_rejected
):
    bundle.quality = {"passed": True}
    source = bundle.sources[0]
    quote = "The paper was first posted on January 22, 2025."
    core = ResearchFinding(
        id="paper-date",
        question_ids=["paper"],
        kind="fact",
        title="论文公开日期",
        text=f"论文公开日期为 {'2025-01-20' if core_fact_rejected else '2025-01-22'}。",
        evidence=[{"source_id": source.id, "quote": quote}],
        limitations="该日期仅代表论文公开，不能代替模型发布日。",
    )
    optional = ResearchFinding(
        id="optional-inference",
        question_ids=["paper"],
        kind="analysis",
        title="额外时间推断",
        text="当前网页含论文链接，因此论文在模型发布当天已公开。",
        evidence=[{"source_id": source.id, "quote": quote}],
        limitations="当前链接不能单独说明过去的公开状态。",
    )
    market = draft_finding().model_copy(update={"id": "market", "question_ids": ["market"]})
    questions = [
        ResearchQuestion(id="paper", question="论文何时公开", acceptance="原文核实日期", kind="event"),
        ResearchQuestion(id="market", question="比较收益", acceptance="确定性结果", kind="market"),
    ]
    reviewed = []

    async def structured(name, schema, context, **kwargs):
        if name == "synthesis":
            return NarrativeDraft(findings=[market, core, optional])
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id=f["id"], inference_audit="逐条检查日期支持与指标引用边界", violations=[]
                    )
                    for f in context["draft"]["findings"]
                ]
            )
        if name == "text-reviewer":
            return NarrativeReview(
                claims=[
                    ClaimVerdict(finding_id="market", verdict="supported", reason="收益引用正确"),
                    ClaimVerdict(
                        finding_id="paper-date",
                        verdict="unsupported" if core_fact_rejected else "supported",
                        reason="所述日期与原文不符" if core_fact_rejected else "原文逐字支持公开日期",
                        repair="retrieve" if core_fact_rejected else "none",
                    ),
                    ClaimVerdict(
                        finding_id="optional-inference",
                        verdict="unsupported",
                        reason="当前链接不能倒推历史公开时间，额外推断不能发布",
                    ),
                ],
                questions=[],
            )
        assert name == "question-review", "纯缺事实时补查；已有完整核心回答时无需改写额外段落"
        ids = {f["id"] for f in context["accepted_findings"]}
        reviewed.append(ids)
        assert "optional-inference" not in ids
        return QuestionCoverageReview(
            questions=[
                QuestionVerdict(question_id="market", answered=True, reason="收益已有已批准依据"),
                QuestionVerdict(
                    question_id="paper",
                    answered="paper-date" in ids,
                    reason="原文已支持确切论文日期" if "paper-date" in ids else "核心日期结论未通过原文核验",
                ),
            ]
        )

    runtime = runtime_for(tmp_path, structured)
    runtime.texts[source.id] = quote
    result = await NarrativeService(runtime, allow_retrieval=True).compose(bundle, questions)

    expected_ids = {"market"} if core_fact_rejected else {"market", "paper-date"}
    assert reviewed == [expected_ids]
    assert {f.id for f in result.findings} == expected_ids
    assert optional.text not in result.text
    paper_question = next(q for q in result.questions if q.id == "paper")
    if core_fact_rejected:
        assert result.status == "partial" and paper_question.status == "insufficient"
        assert core.text not in result.text
        assert any(g.question_id == "paper" for g in result.gaps)
    else:
        assert result.status == "complete" and paper_question.status == "answered"
        assert core.text in result.text and not result.gaps
    assert result.reviews[0]["review"]["claims"][-1]["verdict"] == "unsupported"


async def test_stale_answered_questions_cannot_discard_current_verified_partial(bundle, tmp_path):
    bundle.quality = {"passed": True}
    questions = [
        ResearchQuestion(
            id=qid,
            question=title,
            acceptance="确定性指标",
            kind="market",
            status="answered",
            finding_ids=["old-" + qid],
            gaps=["旧研究状态，不能用作本轮回答依据"],
        )
        for qid, title in [("q", "比较收益"), ("risk", "说明风险")]
    ]
    original_questions = [q.model_dump() for q in questions]
    calls = []

    async def structured(name, schema, context, **kwargs):
        calls.append(name)
        if name == "synthesis":
            return NarrativeDraft(findings=[draft_finding()])
        if name == "text-repair":
            raise TimeoutError("本轮修复中断")
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id="f", inference_audit="只展示已计算收益，不推断未来表现", violations=[]
                    )
                ]
            )
        if name == "text-reviewer":
            return NarrativeReview(
                claims=[ClaimVerdict(finding_id="f", verdict="supported", reason="本轮指标引用已核验")],
                questions=[],
            )
        assert name == "question-review"
        return QuestionCoverageReview(
            questions=[
                QuestionVerdict(question_id="q", answered=True, reason="本轮收益结论有依据"),
                QuestionVerdict(question_id="risk", answered=False, reason="尚缺风险分析"),
            ]
        )

    runtime = runtime_for(tmp_path, structured)
    assessment_path = runtime.root / "research-assessment.json"
    assert not assessment_path.exists()
    result = await NarrativeService(runtime).compose(bundle, questions)
    assert result.status == "partial" and result.text
    assert [f.id for f in result.findings] == ["f"]
    assert result.questions[0].status == "answered" and result.questions[0].finding_ids == ["f"]
    assert result.questions[1].status == "insufficient" and result.questions[1].finding_ids == []
    assert "尚缺风险分析" in result.gaps[0].reason
    assert [q.model_dump() for q in questions] == original_questions
    saved = json.loads(assessment_path.read_text())
    assert saved["status"] == "partial" and saved["findings"][0]["id"] == "f"
    assert calls.count("synthesis") == 1 and calls.count("text-repair") == 1

    # A matching saved assessment remains usable when the next recovery also times out.
    resumed = await NarrativeService(runtime).compose(bundle, questions)
    assert resumed.status == "partial" and resumed.text == result.text
    assert resumed.findings == result.findings and resumed.gaps == result.gaps
    assert calls.count("synthesis") == 1 and calls.count("text-repair") == 2


@pytest.mark.parametrize("correct_second_patch", [True, False])
async def test_invalid_exact_patch_has_one_bounded_retry_and_preserves_audit(
    bundle, tmp_path, correct_second_patch
):
    bundle.quality = {"passed": True}
    questions = [
        ResearchQuestion(id=qid, question=title, acceptance="确定性指标", kind="market")
        for qid, title in [("q", "比较收益"), ("risk", "说明风险")]
    ]
    incorrect = draft_finding().model_copy(
        update={
            "id": "risk-finding",
            "question_ids": ["risk"],
            "title": "历史风险",
            "text": "组合没有损失。回撤为 {{execution.portfolio.max_drawdown}}。",
        }
    )
    calls, patch_contexts = [], []

    async def structured(name, schema, context, **kwargs):
        kwargs["budget"].charge()
        calls.append(name)
        if name == "synthesis":
            return NarrativeDraft(findings=[draft_finding(), incorrect])
        if name == "text-repair":
            patch_contexts.append(deepcopy(context))
            assert len(patch_contexts) <= 2, "同一修复阶段不能无限重试补丁"
            old = "组合没有损失" if correct_second_patch and len(patch_contexts) == 2 else "不存在的原文片段"
            return NarrativePatch(
                edits=[TextEdit(finding_id="risk-finding", field="text", old=old, new="组合经历过回撤")]
            )
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id=f["id"], inference_audit="按本轮确定性指标核对有限历史表述", violations=[]
                    )
                    for f in context["draft"]["findings"]
                ]
            )
        if name == "text-reviewer":
            return NarrativeReview(
                claims=[
                    ClaimVerdict(
                        finding_id=f["id"],
                        verdict="unsupported" if "没有损失" in f["text"] else "supported",
                        reason="风险表述与回撤结果矛盾" if "没有损失" in f["text"] else "指标与文字一致",
                        repair="rewrite" if "没有损失" in f["text"] else "none",
                    )
                    for f in context["draft"]["findings"]
                ],
                questions=[],
            )
        assert name == "question-review"
        ids = {f["id"] for f in context["accepted_findings"]}
        return QuestionCoverageReview(
            questions=[
                QuestionVerdict(question_id="q", answered="f" in ids, reason="逐项检查已批准结论"),
                QuestionVerdict(question_id="risk", answered="risk-finding" in ids, reason="检查风险表述"),
            ]
        )

    runtime = runtime_for(tmp_path, structured)
    result = await NarrativeService(runtime).compose(bundle, questions)
    assert len(patch_contexts) == 2 and calls.count("synthesis") == 1
    attempts = json.loads((runtime.root / "research-text-attempts.json").read_text())
    assert attempts["attempts"] == 2
    assert runtime.budget.model_calls == len(calls) == (9 if correct_second_patch else 6)
    assert "没有损失" not in result.text
    if correct_second_patch:
        assert result.status == "complete"
        assert {f.id for f in result.findings} == {"f", "risk-finding"}
        assert "组合经历过回撤" in result.text
        assert result.reviews[-1]["reused_certificates"] == ["f"]
    else:
        assert result.status == "partial" and [f.id for f in result.findings] == ["f"]
        assert result.questions[1].status == "insufficient"

    # The retry must receive the concrete invalid edit and validation error, not a blind rerun.
    retry_context = json.dumps(patch_contexts[1], ensure_ascii=False)
    assert "不存在的原文片段" in retry_context and "匹配" in retry_context
    saved_json = "\n".join(p.read_text() for p in runtime.root.glob("research-*.json"))
    assert "不存在的原文片段" in saved_json and "匹配" in saved_json


@pytest.mark.parametrize(
    "bad_text,repair_kind",
    [
        ("组合收益为 20%。", "recalculate"),
        ("组合收益为 {{ execution.portfolio.total_return }}。", "rewrite"),
        ("组合收益为 {{execution.portfolio.total_return}}，因此保证未来保本。", "rewrite"),
    ],
)
async def test_local_repair_precedes_retrieval_for_fixable_claim_and_optional_gap(
    bundle, tmp_path, bad_text, repair_kind
):
    bundle.quality = {"passed": True}
    q = ResearchQuestion(
        id="q", question="比较历史收益并说明限制", acceptance="已计算收益与样本边界", kind="market"
    )
    gap = ResearchGap(question_id="q", reason="尚缺独立来源证明稳定保本机制", next_action="寻找机制证明材料")
    safe_text = "本样本组合收益为 {{execution.portfolio.total_return}}，不能据此保证未来保本。"
    initial = draft_finding().model_copy(update={"text": bad_text})
    calls, coverage_contexts = [], []

    async def structured(name, schema, context, **kwargs):
        kwargs["budget"].charge()
        calls.append(name)
        if name == "synthesis":
            return NarrativeDraft(findings=[initial], gaps=[gap])
        if name == "text-repair":
            assert context["repair"]["unresolved_gaps"][0]["reason"] == gap.reason
            return NarrativePatch(edits=[TextEdit(finding_id="f", field="text", old=bad_text, new=safe_text)])
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id="f",
                        inference_audit="测试把未来保本保证改为有限历史结论，仍保留研究边界",
                        violations=[
                            MeaningViolation(
                                quote="因此保证未来保本", reason="历史收益不能保证未来保本", repair="rewrite"
                            )
                        ]
                        if "因此保证" in context["draft"]["findings"][0]["text"]
                        else [],
                    )
                ]
            )
        if name == "text-reviewer":
            corrected = context["draft"]["findings"][0]["text"] == safe_text
            return NarrativeReview(
                claims=[
                    ClaimVerdict(
                        finding_id="f",
                        verdict="supported" if corrected else "unsupported",
                        reason="绑定指标并限制推断" if corrected else "先修正本地可处理的问题",
                        repair="none" if corrected else repair_kind,
                    )
                ],
                questions=[],
            )
        assert name == "question-review"
        coverage_contexts.append(deepcopy(context))
        corrected = bool(context["accepted_findings"])
        assert context["open_gaps"][0]["id"] == gap_id(gap)
        return QuestionCoverageReview(
            questions=[
                QuestionVerdict(
                    question_id="q",
                    answered=corrected,
                    reason="已回答请求的历史收益与限制；额外机制证明不是本题要求"
                    if corrected
                    else "只有被拒草稿，尚不能判断覆盖",
                    resolved_gaps=[
                        GapResolution(
                            gap_id=gap_id(gap),
                            finding_id="f",
                            quote=safe_text,
                            reason="已核验的历史收益与边界回答原要求，稳定保本机制是额外证明要求",
                        )
                    ]
                    if corrected
                    else [],
                )
            ]
        )

    runtime = runtime_for(tmp_path, structured)
    result = await NarrativeService(runtime, allow_retrieval=True).compose(bundle, [q])
    assert result.status == "complete" and not result.gaps
    assert calls.count("text-repair") == 1 and calls.count("question-review") == 2
    assert coverage_contexts[0]["accepted_findings"] == []
    assert coverage_contexts[1]["accepted_findings"][0]["text"] == safe_text
    assert calls.index("text-repair") > calls.index("question-review")
    assert calls[-1] == "question-review" and runtime.budget.model_calls == 8
    assert len(result.reviews) == 2


@pytest.mark.parametrize("rejected_date_claim", [False, True])
async def test_pure_missing_evidence_returns_for_retrieval_without_local_rewrite(
    bundle, tmp_path, rejected_date_claim
):
    bundle.quality = {"passed": True}
    questions = [
        ResearchQuestion(id="q", question="比较收益", acceptance="确定性结果", kind="market"),
        ResearchQuestion(id="release", question="核实论文公开日期", acceptance="原文日期证据", kind="event"),
    ]
    gap = ResearchGap(question_id="release", reason="缺少论文公开日期的原文证据", next_action="读取论文原文")
    drafts = [draft_finding()]
    if rejected_date_claim:
        drafts.append(
            draft_finding().model_copy(
                update={
                    "id": "date-finding",
                    "question_ids": ["release"],
                    "text": "论文日期未知；同期累计收益为 {{execution.portfolio.total_return}}。",
                }
            )
        )
    calls = []

    async def structured(name, schema, context, **kwargs):
        calls.append(name)
        if name == "synthesis":
            return NarrativeDraft(findings=drafts, gaps=[gap])
        if name == "meaning-review":
            return MeaningReview(
                checks=[
                    MeaningCheck(
                        finding_id=f["id"],
                        inference_audit="未扩展事件事实；日期须由原始证据补齐",
                        violations=[],
                    )
                    for f in context["draft"]["findings"]
                ]
            )
        if name == "text-reviewer":
            return NarrativeReview(
                claims=[
                    ClaimVerdict(
                        finding_id=f["id"],
                        verdict="supported" if f["id"] == "f" else "unsupported",
                        reason="指标已有依据" if f["id"] == "f" else "缺少论文日期证据",
                        repair="none" if f["id"] == "f" else "retrieve",
                    )
                    for f in context["draft"]["findings"]
                ],
                questions=[],
            )
        assert name == "question-review", "纯缺证据时不应消耗本地改写轮次"
        assert [f["id"] for f in context["accepted_findings"]] == ["f"]
        return QuestionCoverageReview(
            questions=[
                QuestionVerdict(question_id="q", answered=True, reason="收益已有依据"),
                QuestionVerdict(
                    question_id="release", answered=False, reason="未知日期不是用户要求的发布日期"
                ),
            ]
        )

    runtime = runtime_for(tmp_path, structured)
    result = await NarrativeService(runtime, allow_retrieval=True).compose(bundle, questions)
    assert result.status == "partial" and [f.id for f in result.findings] == ["f"]
    assert len(result.reviews) == 1 and len(calls) == 4 and "text-repair" not in calls
    assert result.questions[1].status == "insufficient"
    assert any("缺少论文公开日期" in g.reason for g in result.gaps)
    state = json.loads((runtime.root / "research-text-attempts.json").read_text())
    assert state["attempts"] == 1
    assert state["last_repair"]["unresolved_gaps"][0]["next_action"] == "读取论文原文"
