"""Deterministic report wording shared by Word and PowerPoint."""

from .domain import ResearchBundle


def percent(value):
    return "—" if value is None else f"{value:+.1%}"


def key_points(bundle: ResearchBundle) -> list[str]:
    points = [claim.text for claim in bundle.claims]
    anchors = bundle.comparison.get("anchors", [])
    if anchors:
        points = [
            f"{row['symbol']}：共同月末区间 {anchors[0]['date']} 至 {anchors[-1]['date']}，"
            f"累计收益 {percent(row['total_return'])}，月末估值最大回撤 {percent(row['max_drawdown'])}。"
            for row in bundle.comparison.get("asset_metrics", [])
        ]
    for row in bundle.comparison.get("inflation_summary", []):
        points.append(
            f"在事后选取的 {row['stress_n']} 个基准最差月份中，{row['symbol']} 有 {row['stress_positive_months']} 个月收益为正。该结果衡量特定压力样本，不能推广为所有危机中有效。"
        )
    return points


def decisions(bundle: ResearchBundle) -> list[list[str]]:
    if len(bundle.spec.symbols) > 1:
        return [
            [
                "避险",
                "基准下跌期间是否保值",
                "压力月份收益、最大回撤、滚动相关性",
                "仅在已检验情景成立时接受，避免用长期涨幅代替危机表现",
            ],
            [
                "抗通胀",
                "能否维持实际购买力",
                "CPI 调整净值、高通胀月份收益",
                "区分多年购买力与短期 CPI 波动，月度相关性不代表因果",
            ],
            [
                "资产配置",
                "分散化是否改善风险",
                "组合回撤、波动、交易成本与漂移",
                "先设权重和再平衡规则，再检验结果；不在全样本寻找最优权重",
            ],
            [
                "执行",
                "能否按假设成交",
                "实际时间戳、下一开盘成交、现金台账",
                "识别交易日差异，保留滑点、流动性与跟踪误差的敏感性",
            ],
        ]
    return [
        ["事件", "发布了什么", "公开原文、日期和精度", "先核实事件及标的相关性"],
        ["行情", "变化何时确认", "复权日线、事前波动、成交量", "回顾拐点保留后续确认日期"],
        ["反应", "窗口相对表现", "1/5/20 日收益减基准收益", "反应等级为描述性指标"],
        ["关联", "是否存在其他解释", "来源强度、时序与同期事件", "关联不等于因果，证据不足时保留未知"],
    ]


def limitations(bundle: ResearchBundle) -> list[str]:
    return [
        "免费公开数据可能延迟、修订或暂时不可用。采集时间与快照哈希固定本次可复核范围。",
        "日线无法隔离公告前后的盘中交易。日期级来源保留盘前/盘后不确定性，市场反应等级不表示因果概率。",
        "回测采用固定事前权重，交易成本按成交额扣除。月度公式近似与下一开盘执行分别报告。",
        "宏观数据为当前可得历史版本，压力月份为全样本事后选择。二者仅用于解释，不进入交易信号。",
        *bundle.warnings[:5],
    ]
