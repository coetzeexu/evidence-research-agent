"""Predeclared one-factor sensitivity checks. Never select a hindsight-optimal allocation."""

from .analytics import portfolio_backtest
from .domain import ResearchSpec


def sensitivity_analysis(spec, datasets, anchors):
    variants = [("baseline", "原始配置", {}, anchors)]
    for cost in [0, 10, 25, 50]:
        if cost != spec.cost_bps:
            variants.append(("cost", f"成本 {cost} bps", {"cost_bps": cost}, anchors))
    for months in [0, 1, 3, 12]:
        if months != spec.rebalance_months:
            variants.append(
                (
                    "frequency",
                    "买入持有" if not months else f"每 {months} 月再平衡",
                    {"rebalance_months": months},
                    anchors,
                )
            )
    if len(spec.symbols) == 2:
        for weight in [0.2, 0.5, 0.8]:
            if abs(weight - spec.weights[0]) > 1e-8:
                variants.append(
                    ("weights", f"{spec.symbols[0]} {weight:.0%}", {"weights": [weight, 1 - weight]}, anchors)
                )
    if len(anchors) >= 26:
        middle = len(anchors) // 2
        variants.extend(
            [("period", "前半区间", {}, anchors[: middle + 1]), ("period", "后半区间", {}, anchors[middle:])]
        )
    rows = []
    for dimension, label, updates, sample in variants:
        config = ResearchSpec.model_validate({**spec.model_dump(), **updates})
        result = portfolio_backtest(sample, config, datasets)
        rows.append(
            {
                "dimension": dimension,
                "label": label,
                "start": sample[0]["date"],
                "end": sample[-1]["date"],
                "observations": len(sample),
                "weights": config.weights,
                "cost_bps": config.cost_bps,
                "rebalance_months": config.rebalance_months,
                **result["metrics"],
                "total_cost": sum(t["cost"] for t in result["trades"]),
            }
        )
    return {
        "method": "固定网格逐项改变一个参数；全部使用下一可交易开盘执行口径。",
        "rows": rows,
        "dataset_ids": [datasets[s].id for s in spec.symbols],
        "caveat": "分段结果为历史稳健性检查，不是样本外检验；不同期限比较应看年化及风险，"
        "不以全样本最优结果推荐配置。Excel 中该表为快照，不随蓝色输入格重算。",
    }
