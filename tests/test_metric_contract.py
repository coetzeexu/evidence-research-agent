"""Regression of real published unit errors and fail-closed metric registration."""

import pytest
from pydantic import ValidationError
from research_app.research_contract import ResearchAssessment
from research_app.research_metrics import display_metric, metric_catalog
from research_app.research_text import render_research


def test_annualization_frequency_is_a_count_not_a_percentage(bundle):
    metrics = metric_catalog(bundle)
    for prefix in ("execution.portfolio", "execution.GLD", "monthly.BTC-USD"):
        frequency = metrics[f"{prefix}.frequency"]
        assert frequency.unit == "integer"
        assert display_metric(frequency) == "12"
        assert "年化" in frequency.meaning and "再平衡" in frequency.meaning
    assert metrics["config.rebalance_months"].meaning != frequency.meaning


def test_new_numeric_fields_require_an_explicit_contract(bundle):
    bundle.comparison["backtest"]["metrics"]["undocumented_count"] = 12
    with pytest.raises(ValueError, match="undocumented_count"):
        metric_catalog(bundle)


def test_price_observations_return_pairs_and_cpi_pairs_are_distinct(bundle):
    bundle.comparison["inflation_summary"][0].update(high_inflation_n=7, low_inflation_n=3)
    metrics = metric_catalog(bundle)
    observations = metrics["execution.portfolio.observations"]
    returns = metrics["execution.portfolio.return_observations"]
    inflation = metrics["inflation.GLD.n"]
    assert observations.value == len(bundle.comparison["anchors"])
    assert returns.value == observations.value - 1
    assert inflation.value == 10
    assert len({m.meaning for m in (observations, returns, inflation)}) == 3
    assert all(m.unit == "integer" for m in (observations, returns, inflation))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_metrics_cannot_be_published(bundle, value):
    payload = metric_catalog(bundle)["execution.portfolio.total_return"].model_dump()
    payload["value"] = value
    with pytest.raises(ValidationError):
        type(metric_catalog(bundle)["execution.portfolio.total_return"]).model_validate(payload)


def test_fractional_count_cannot_silently_round(bundle):
    payload = metric_catalog(bundle)["config.anchors"].model_dump()
    payload["value"] = 3.5
    with pytest.raises(ValidationError):
        type(metric_catalog(bundle)["config.anchors"]).model_validate(payload)


def test_real_failed_frequency_sentence_renders_correctly_in_all_fields(bundle):
    from research_app.research_contract import ResearchFinding

    finding = ResearchFinding(
        id="frequency-regression",
        question_ids=["market"],
        kind="analysis",
        title="每年 {{execution.portfolio.frequency}} 个估值周期",
        text="年化换算使用每年 {{execution.portfolio.frequency}} 个周期。",
        limitations="与每 {{config.rebalance_months}} 月再平衡不同。",
    )
    assessment = ResearchAssessment(
        status="complete", findings=[finding], metrics=list(metric_catalog(bundle).values())
    )
    text = render_research(assessment, bundle)
    assert "每年 12 个估值周期" in text
    assert "每年 12 个周期" in text
    assert "1200" not in text and "{{" not in text


def test_units_and_precision_preserve_sign_cost_currency_and_ratio(bundle):
    metrics = metric_catalog(bundle)
    values = [
        ("execution.portfolio.total_return", -0.01234, "-1.23%"),
        ("config.cost_bps", 12.5, "12.5 bps"),
        ("latest.GLD.close", 1234.567, "1,234.57 美元"),
        ("correlation.GLD.BTC-USD.value", -0.1524, "-0.152"),
        ("config.anchors", 1255, "1,255"),
    ]
    for key, value, expected in values:
        assert display_metric(metrics[key].model_copy(update={"value": value})) == expected


@pytest.mark.parametrize(
    "text",
    [
        "年化周期 {{execution.portfolio.frequency}}%。",
        "收益 {{execution.portfolio.total_return}}%。",
        "CPI相关系数基于59个月度观测，收益为 {{execution.portfolio.total_return}}。",
    ],
)
def test_wrong_units_and_unbound_sample_counts_fail_publication(bundle, text):
    from research_app.research_contract import NarrativeDraft, ResearchFinding, ResearchQuestion
    from research_app.research_text import validate_draft

    finding = ResearchFinding(
        id="f", question_ids=["market"], kind="analysis", title="复核", text=text, limitations="历史样本。"
    )
    question = ResearchQuestion(id="market", question="市场", acceptance="可复核", kind="market")
    errors, _ = validate_draft(
        NarrativeDraft(findings=[finding]), bundle, [question], {}, metric_catalog(bundle)
    )
    assert errors.get("f")


@pytest.mark.parametrize("count,total,expected", [(3, 6, False), (4, 6, True), (6, 6, True), (0, 0, False)])
def test_majority_means_strictly_more_than_half(count, total, expected):
    from research_app.research_logic import relationship

    assert relationship("majority", [count, total]) is expected


@pytest.mark.parametrize(
    "text,blocked",
    [
        ("两者均保值，但通胀关联为负、机制不成立", True),
        ("本样本相关性不能证明抗通胀机制不成立", False),
        ("实际购买力提高，但无稳定抗通胀机制", True),
        ("历史样本不足以证明稳定抗通胀机制成立", False),
    ],
)
def test_descriptive_cpi_metrics_do_not_establish_or_disprove_a_mechanism(text, blocked):
    from research_app.research_contract import MeaningCheck, MeaningReview, NarrativeDraft, ResearchFinding
    from research_app.research_semantics import verify_meaning

    finding = ResearchFinding(
        id="f",
        question_ids=["inflation"],
        kind="analysis",
        title=text,
        text="观察结果。",
        limitations="有限样本。",
    )
    review = MeaningReview(
        checks=[
            MeaningCheck(finding_id="f", inference_audit="模型错误放行时程序仍执行边界检查", violations=[])
        ]
    )
    assert bool(verify_meaning(NarrativeDraft(findings=[finding]), review)) is blocked


def test_real_failed_blackwell_claim_cannot_pass_with_old_reviewer_certificate():
    from pathlib import Path

    from research_app.config import PROJECT_ROOT
    from research_app.domain import ResearchBundle
    from research_app.research_contract import NarrativeDraft, NarrativeReview
    from research_app.research_logic import verify_relationships

    path = PROJECT_ROOT / "evals/text-research/Acceptance20260929EventsE/nvda-ab95141d29e24af5.bundle.json"
    saved = ResearchBundle.model_validate_json(Path(path).read_text())
    finding = next(f for f in saved.research.findings if f.id == "f-blackwell")
    audits = [a for a in saved.research.reviews if finding.id in a.get("accepted_hashes", {})]
    review = NarrativeReview.model_validate(audits[-1]["review"])
    errors, _ = verify_relationships(NarrativeDraft(findings=[finding]), review, metric_catalog(saved))
    assert "窗口对照不成立" in " ".join(errors[finding.id])


def test_reviewer_cannot_replace_lowest_claim_with_a_true_increasing_sequence():
    from research_app.config import PROJECT_ROOT
    from research_app.domain import ResearchBundle
    from research_app.research_contract import NarrativeDraft, NarrativeReview
    from research_app.research_logic import verify_relationships

    path = (
        PROJECT_ROOT / "evals/text-research/P0ContractGold20260929/gold-bitcoin-05e996e509b9452d.bundle.json"
    )
    bundle = ResearchBundle.model_validate_json(path.read_text())
    finding = next(f for f in bundle.research.findings if f.id == "f6")
    audits = [a for a in bundle.research.reviews if finding.id in a.get("accepted_hashes", {})]
    review = NarrativeReview.model_validate(audits[-1]["review"])
    errors, _ = verify_relationships(NarrativeDraft(findings=[finding]), review, metric_catalog(bundle))
    assert errors.get(finding.id)


@pytest.mark.parametrize(
    "values,expected", [([1, 2, 3], False), ([3, 2, 1], False), ([1, 1, 2], False), ([1, 3, 2], True)]
)
def test_non_monotonic_claim_requires_a_direction_change(values, expected):
    from research_app.research_logic import relationship

    assert relationship("not_monotonic", values) is expected
