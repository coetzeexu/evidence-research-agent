"""Native editable PPT export using the selected ppt-master ledger style subset."""

import json
import math
import re
import unicodedata
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from .analytics import month_end_anchors
from .config import PROJECT_ROOT
from .domain import ResearchBundle
from .report_content import decisions, key_points, percent
from .security import allowed_link

PPT_SKILL = PROJECT_ROOT / "skills" / "ppt-ledger"


def _line_height(size):
    return size * 1.4 / 72


def _numeric(value):
    return bool(re.fullmatch(r"[+−\-\d.,%/\s]+(?:pp)?|—", str(value)))


def _row_height(row, widths, size, minimum=0.6):
    lines = max(len(_wrap(str(v), widths[i] - 0.25, size)) for i, v in enumerate(row))
    return max(minimum, lines * _line_height(size) + 0.16)


def _text_units(value: str) -> float:
    return sum(1 if unicodedata.east_asian_width(c) in {"W", "F"} else 0.65 for c in value)


def _wrap(value: str, width: float, size: float) -> list[str]:
    """Conservative CJK-aware line breaking; never silently discard research text."""
    capacity = width * 72 / size * 0.93
    result = []
    for paragraph in str(value).split("\n"):
        line = ""
        # Keep numeric values, percentages and Latin symbols intact across lines.
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9.,%/+_-]*|.", paragraph):
            if line and _text_units(line + token) > capacity:
                result.append(line)
                line = ""
            line += token
        result.append(line)
    return result


class LedgerDeck:
    def __init__(self, bundle: ResearchBundle):
        self.bundle = bundle
        self.method = (PPT_SKILL / "references" / "operating-review.md").read_text()
        if "style_id: operating-review" not in self.method:
            raise ValueError("PPT method template must be operating-review")
        self.style = json.loads((PPT_SKILL / "design-tokens.json").read_text())
        self.colors = self.style["colors"]
        self.fonts = self.style["fonts"]
        self.layout = self.style["layout"]
        self.prs = Presentation()
        self.prs.slide_width = Inches(self.style["canvas"]["width_inches"])
        self.prs.slide_height = Inches(self.style["canvas"]["height_inches"])
        self.prs.core_properties.author = "Evidence"
        self.prs.core_properties.title = bundle.spec.title
        self.prs.core_properties.subject = "operating-review / 账页式研究决策稿"
        self.prs.core_properties.keywords = self.style["template"]
        self.market_refs = [
            (symbol, dataset.source_url)
            for symbol, dataset in bundle.datasets.items()
            if symbol in [*bundle.spec.symbols, bundle.spec.benchmark]
        ]

    def color(self, name):
        return RGBColor.from_string(self.colors.get(name, name))

    def text(
        self,
        slide,
        value,
        x,
        y,
        w,
        h,
        size=18,
        color="primary",
        bold=False,
        numeric=False,
        url=None,
        align=PP_ALIGN.LEFT,
    ):
        h = max(h, len(str(value).split("\n")) * _line_height(size) + 0.03)
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        box.name = "ledger-text"
        tf = box.text_frame
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.word_wrap = False
        tf.vertical_anchor = MSO_ANCHOR.TOP
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        for i, line in enumerate(str(value).split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_before = p.space_after = Pt(0)
            p.line_spacing = Pt(size * 1.4)
            p.alignment = align
            run = p.add_run()
            run.text = line
            run.font.name = self.fonts["data" if numeric else "body"]
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = self.color(color)
            ea = OxmlElement("a:ea")
            ea.set("typeface", self.fonts["body"])
            run._r.get_or_add_rPr().append(ea)
            if url and allowed_link(url):
                run.hyperlink.address = url
        return box

    def rule(self, slide, y, x=0.667, w=12, color="divider", thickness=0.7):
        shape = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y), Inches(x + w), Inches(y)
        )
        shape.name = "ledger-rule"
        shape.line.color.rgb = self.color(color)
        shape.line.width = Pt(thickness)
        shape._element.spPr.append(OxmlElement("a:effectLst"))
        for style in list(shape._element):
            if style.tag.endswith("}style"):
                shape._element.remove(style)

    def page(self, title, subtitle="", refs=None, field="", cover=False):
        s = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = self.color("background")
        if not cover:
            self.text(s, title, 0.667, 0.5, 12, 0.65, self.style["font_points"]["title"], bold=True)
            self.text(s, subtitle, 0.667, 1.27, 12, 0.5, 14, "muted")
            self.rule(s, self.layout["header_rule_y"], color="primary", thickness=1.1)
        self.rule(s, self.layout["footer_rule_y"])
        links = self.market_refs if refs is None else refs
        self.text(s, "来源", 0.667, 6.94, 0.5, 0.22, 10, "muted")
        x = 1.18
        for label, url in links[:4]:
            label = label.removeprefix("www.")
            label = label if len(label) < 28 else label[:26] + "…"
            width = min(2.4, max(0.7, _text_units(label) * 0.16))
            box = self.text(s, label, x, 6.92, width, 0.28, 10, "accent", url=url)
            box.text_frame.word_wrap = False
            x += width + 0.17
        self.text(
            s,
            f"{len(self.prs.slides):02}",
            12.08,
            6.92,
            0.55,
            0.28,
            11,
            "muted",
            numeric=True,
            align=PP_ALIGN.RIGHT,
        )
        notes = [
            f"研究区间：{self.bundle.spec.start} 至 {self.bundle.spec.end}",
            f"数据字段：{field}",
            "本页来源：",
        ]
        notes.extend(f"{label}: {url}" for label, url in links if allowed_link(url))
        notes.extend(
            f"数据快照 {d.id}: SHA-256 {d.content_hash}; 提取时间 {d.retrieved_at}; {d.source_url}"
            for d in self.bundle.datasets.values()
        )
        notes.append("反应等级为描述性关联，不证明因果；历史表现不保证未来结果。")
        s.notes_slide.notes_text_frame.text = "\n".join(notes)
        return s

    def table(self, slide, headers, rows, widths, y=2.23, size=17):
        heights = [_row_height(headers, widths, size - 1, 0.51)]
        heights.extend(_row_height(row, widths, size) for row in rows)
        numeric_columns = [bool(rows) and all(_numeric(r[i]) for r in rows) for i in range(len(headers))]
        table = slide.shapes.add_table(
            len(rows) + 1, len(headers), Inches(0.667), Inches(y), Inches(sum(widths)), Inches(sum(heights))
        ).table
        table.first_row = False
        table.horz_banding = False
        for col, width in zip(table.columns, widths, strict=True):
            col.width = Inches(width)
        for ri, row in enumerate([headers, *rows]):
            table.rows[ri].height = Inches(heights[ri])
            for ci, value in enumerate(row):
                cell = table.cell(ri, ci)
                numeric = numeric_columns[ci]
                point_size = size if ri else size - 1
                cell.text = "\n".join(_wrap(str(value), widths[ci] - 0.25, point_size))
                cell.text_frame.auto_size = MSO_AUTO_SIZE.NONE
                cell.text_frame.word_wrap = False
                cell.margin_left = cell.margin_right = Inches(0.12)
                cell.margin_top = cell.margin_bottom = Inches(0.07)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.fill.solid()
                cell.fill.fore_color.rgb = self.color("primary" if ri == 0 else "background")
                for p in cell.text_frame.paragraphs:
                    p.alignment = PP_ALIGN.RIGHT if numeric else PP_ALIGN.LEFT
                    p.space_before = p.space_after = Pt(0)
                    p.line_spacing = Pt(point_size * 1.4)
                    for r in p.runs:
                        r.font.name = self.fonts["data" if numeric and ri else "body"]
                        r.font.size = Pt(point_size)
                        r.font.bold = ri == 0
                        r.font.color.rgb = self.color("background" if ri == 0 else "primary")
                        ea = OxmlElement("a:ea")
                        ea.set("typeface", self.fonts["body"])
                        r._r.get_or_add_rPr().append(ea)
                tcpr = cell._tc.get_or_add_tcPr()
                for edge in ("lnL", "lnR", "lnT", "lnB"):
                    line = OxmlElement("a:" + edge)
                    line.set("w", "6350")
                    if edge == "lnB":
                        fill = OxmlElement("a:solidFill")
                        rgb = OxmlElement("a:srgbClr")
                        rgb.set("val", self.colors["divider"])
                        fill.append(rgb)
                        line.append(fill)
                    else:
                        line.append(OxmlElement("a:noFill"))
                    tcpr.append(line)
        return sum(heights)

    def table_pages(self, title, subtitle, headers, rows, widths, field, refs=None, size=17):
        # Measure content before pagination. No hard row cap or silent [:N] truncation.
        chunk = []
        header_height = _row_height(headers, widths, size - 1, 0.51)
        height = header_height
        for row in rows:
            row_height = _row_height(row, widths, size)
            if chunk and height + row_height > 4.25:
                s = self.page(title, subtitle, refs, field)
                self.table(s, headers, chunk, widths, size=size)
                chunk, height = [], header_height
            chunk.append(row)
            height += row_height
        if chunk:
            s = self.page(title, subtitle, refs, field)
            self.table(s, headers, chunk, widths, size=size)

    def prose_pages(self, title, entries, subtitle="", refs=None, field=""):
        s, y = None, 2.2
        leading, padding, gap = _line_height(18), 0.12, 0.25
        for label, value in entries:
            lines = _wrap(str(value), 9.0, 18)
            while lines:
                if s is None or y + 0.75 > 6.5:
                    s = self.page(title, subtitle, refs, field)
                    y = 2.2
                capacity = max(1, math.floor((6.45 - y - padding) / leading))
                chosen, lines = lines[:capacity], lines[capacity:]
                self.text(s, label, 0.667, y, 2.4, 0.55, 17, "accent", True)
                height = max(0.55, len(chosen) * leading + padding)
                self.text(s, "\n".join(chosen), 3.32, y, 9.0, height, 18)
                y += height + gap
                if lines:
                    s = None
                elif y < 6.45:
                    self.rule(s, y - 0.13)

    def chart(self, slide, dates, series):
        data = CategoryChartData()
        data.categories = [d[:7] for d in dates]
        for name, values in series:
            data.add_series(name, values)
        c = slide.shapes.add_chart(
            XL_CHART_TYPE.LINE, Inches(0.6), Inches(2.19), Inches(12.03), Inches(4.28), data
        ).chart
        c.has_legend = True
        c.legend.position = XL_LEGEND_POSITION.BOTTOM
        c.legend.include_in_layout = False
        c.legend.font.name = self.fonts["body"]
        c.legend.font.size = Pt(12)
        c.chart_style = 13
        for i, line in enumerate(c.series):
            line.format.line.color.rgb = RGBColor.from_string(self.colors["series"][i % 5])
            line.format.line.width = Pt(2.2)
            line.smooth = False
        c.category_axis.tick_labels.font.size = Pt(10)
        c.category_axis.tick_label_spacing = max(1, len(dates) // 10)
        c.value_axis.tick_labels.font.size = Pt(11)
        c.value_axis.tick_labels.number_format = "0"
        c.value_axis.has_major_gridlines = True
        c.value_axis.major_gridlines.format.line.color.rgb = self.color("grid")
        return c


def export_slides(bundle: ResearchBundle, target: Path):
    deck = LedgerDeck(bundle)
    metrics = bundle.comparison.get("asset_metrics") or [
        m for m in bundle.metrics if m["id"].startswith("performance-")
    ]
    s = deck.page("", field="comparison.asset_metrics / metrics.performance-*", cover=True)
    deck.text(s, "EVIDENCE  /  研究决策稿", 0.667, 0.7, 10, 0.4, 14, "muted")
    title_lines = _wrap(bundle.spec.title, 11.9, 45)
    long_title = len(title_lines) > 2
    cover_title = bundle.spec.title
    if long_title:
        cover_title = (
            "黄金与比特币\n避险与抗通胀比较"
            if {"GLD", "BTC-USD"}.issubset(bundle.spec.symbols)
            else " / ".join(bundle.spec.symbols) + "\n行情与事件研究"
        )
    cover_lines = _wrap(cover_title, 11.9, 45)
    # Arbitrarily long user titles continue in the next page, preserving the full value.
    deck.text(s, "\n".join(cover_lines[:3]), 0.667, 1.48, 12, 2.45, 45, bold=True)
    deck.rule(s, 4.0, w=12, color="primary", thickness=1.6)
    deck.text(s, f"{bundle.spec.start} 至 {bundle.spec.end}", 0.667, 4.2, 12, 0.35, 14, "muted")
    for i, metric in enumerate(metrics[:3]):
        x = 0.667 + 4.04 * i
        deck.text(s, f"{metric['symbol']}  累计收益", x, 4.86, 3.65, 0.35, 15, "muted")
        deck.text(
            s, percent(metric.get("total_return")), x, 5.27, 3.65, 0.8, 43, "accent", True, numeric=True
        )
        deck.text(s, "最大回撤 " + percent(metric.get("max_drawdown")), x, 6.18, 3.65, 0.38, 16)
    if long_title:
        deck.prose_pages("研究主题", [("主题", bundle.spec.title)])

    deck.table_pages(
        "收益与风险",
        "共同月末估值口径；收益与风险均为历史描述。"
        if bundle.comparison.get("asset_metrics")
        else "各资产自身日度区间，实际起止可能不同。",
        ["资产", "累计收益", "年化收益", "年化波动", "最大回撤"],
        [
            [
                m["symbol"],
                percent(m["total_return"]),
                percent(m["cagr"]),
                percent(m["volatility"]),
                percent(m["max_drawdown"]),
            ]
            for m in metrics
        ],
        [2.0, 2.5, 2.5, 2.5, 2.5],
        "comparison.asset_metrics / metrics.performance-*",
    )
    # Operating-review: explicit result → variance. No fabricated plan values.
    # Compare only the same common-monthly metrics; daily windows may differ.
    if bundle.comparison.get("asset_metrics") and len(metrics) > 1:
        base = metrics[0]
        others = metrics[1:]
        deck.table_pages(
            "同口径资产差异",
            f"以 {base['symbol']} 为比较项，差值单位为百分点；无计划值，不设虚构目标。",
            ["比较项", "累计收益差", "年化收益差", "最大回撤差"],
            [
                [
                    f"{m['symbol']} − {base['symbol']}",
                    f"{(m['total_return'] - base['total_return']) * 100:+.2f} pp",
                    f"{(m['cagr'] - base['cagr']) * 100:+.2f} pp",
                    f"{(m['max_drawdown'] - base['max_drawdown']) * 100:+.2f} pp",
                ]
                for m in others
            ],
            [4.0, 2.65, 2.65, 2.7],
            "comparison.asset_metrics; difference = asset − first asset",
        )
    # The method requires causes to be distinguished from observations. Financial
    # event windows and CPI groups are descriptive, so do not invent a driver bridge.
    deck.prose_pages(
        "差异解释与证据边界",
        [
            ("已观察到的结果", "收益、回撤与压力月份表现来自同一数据快照，后续图表与分组表提供检验依据。"),
            (
                "原因尚未确立",
                "行情窗口、通胀分组与同期事件仅提供关联证据，未进行因果识别，不能据此断言某事件导致价格变化。",
            ),
            (
                "待验证问题",
                "区分共同市场波动与标的特有反应，检查基准、窗口长度和配置参数变化后判断是否仍成立。",
            ),
        ],
        "事实、解释与待验证问题分开呈现；缺失的机制证据不以叙事补齐。",
        field="comparison / annotations / causal limitations",
    )
    points = key_points(bundle)
    if points:
        deck.prose_pages(
            "研究要点",
            [(f"{i + 1:02}", p) for i, p in enumerate(points)],
            "判断与限定条件共同构成结论。",
            field="claims / comparison.asset_metrics / inflation_summary",
        )

    series = bundle.comparison.get("series", [])
    if not series and bundle.comparison.get("available") is not False:
        anchors = month_end_anchors(bundle.datasets, bundle.spec.symbols, bundle.spec.start, bundle.spec.end)
        if anchors:
            series = [
                {
                    "symbol": sym,
                    "dates": [r["date"] for r in anchors],
                    "normalized": [r["prices"][sym] / anchors[0]["prices"][sym] * 100 for r in anchors],
                }
                for sym in bundle.spec.symbols
            ]
    if series:
        s = deck.page(
            "共同估值下的价格表现",
            "初始净值 = 100；相同月末锚点，价格水平已归一化。",
            field="comparison.series.normalized / month_end_anchors",
        )
        deck.chart(s, series[0]["dates"], [(r["symbol"], r["normalized"]) for r in series])

    stress = bundle.comparison.get("stress_periods", [])
    if stress:
        widths = [2.0] + [10 / (len(bundle.spec.symbols) + 1)] * (len(bundle.spec.symbols) + 1)
        deck.table_pages(
            "压力样本中的资产表现",
            f"全样本事后选取 {bundle.spec.benchmark} 最差月份；不代表全部危机。",
            ["月份", bundle.spec.benchmark, *bundle.spec.symbols],
            [
                [
                    r["date"][:7],
                    percent(r["benchmark_return"]),
                    *[percent(r["returns"][sym]) for sym in bundle.spec.symbols],
                ]
                for r in stress
            ],
            widths,
            "comparison.stress_periods",
        )
    inflation = bundle.comparison.get("inflation_summary", [])
    if inflation:
        deck.table_pages(
            "通胀分组与购买力判断",
            "CPI 同比 ≥ 3% 为高通胀组；当前历史版本，分组与相关性均不证明机制。",
            ["资产", "高通胀月均收益", "低通胀月均收益", "月数（高/低）", "CPI 相关系数"],
            [
                [
                    r["symbol"],
                    percent(r["high_inflation_mean_return"]),
                    percent(r["low_inflation_mean_return"]),
                    f"{r['high_inflation_n']} / {r['low_inflation_n']}",
                    "—" if r["inflation_correlation"] is None else f"{r['inflation_correlation']:+.3f}",
                ]
                for r in inflation
            ],
            [1.75, 2.65, 2.65, 2.05, 2.9],
            "comparison.inflation_summary",
            refs=[(s.title, s.url) for s in bundle.sources if "CPI" in s.title or "CPI" in s.url]
            + deck.market_refs,
        )

    backtest = bundle.comparison.get("backtest", {}).get("metrics", {})
    if backtest:
        deck.table_pages(
            "固定权重组合回测",
            "下一开盘执行；成本按成交金额扣除，权重与再平衡参数事先固定。",
            ["配置", "累计收益", "年化收益", "年化波动", "最大回撤"],
            [
                [
                    "组合",
                    percent(backtest.get("total_return")),
                    percent(backtest.get("cagr")),
                    percent(backtest.get("volatility")),
                    percent(backtest.get("max_drawdown")),
                ]
            ],
            [2, 2.5, 2.5, 2.5, 2.5],
            "comparison.backtest.metrics",
        )
    sensitivity = bundle.comparison.get("sensitivity", {}).get("rows", [])
    if sensitivity:
        deck.table_pages(
            "配置敏感性",
            "逐项改变一个参数；分段为历史稳健性检查，不是样本外检验。",
            ["情景", "区间", "年化收益", "最大回撤"],
            [
                [r["label"], f"{r['start']}\n{r['end']}", percent(r["cagr"]), percent(r["max_drawdown"])]
                for r in sensitivity
            ],
            [4.0, 3.0, 2.5, 2.5],
            "comparison.sensitivity.rows",
        )
    for goal, question, indicators, condition in decisions(bundle):
        deck.prose_pages(
            f"决策框架：{goal}",
            [("待回答问题", question), ("检验指标", indicators), ("接受条件", condition)],
            field="deterministic decision framework",
        )

    for event in bundle.events:
        sources = [source for source in bundle.sources if source.id in event.source_ids]
        refs = [(source.publisher, source.url) for source in sources]
        rows = [("事件日期", str(event.date)), ("事件事实", event.summary)]
        for annotation in (a for a in bundle.annotations if a["event_id"] == event.id):
            windows = "；".join(
                f"{w['days']} 日相对收益 {percent(w.get('relative_return'))}" for w in annotation["windows"]
            )
            rows.append((annotation["symbol"], f"{windows}。反应评级：{annotation['rating']}。"))
        deck.prose_pages(
            "事件证据",
            [("事件", event.title), *rows],
            "日期级来源保留盘前/盘后不确定性；窗口收益不能独立证明因果。",
            refs,
            f"events.{event.id} / annotations.event_id={event.id}",
        )
    for d in bundle.disclosures:
        deck.prose_pages(
            "产品定义与适用边界",
            [("产品定义", d["description"]), ("采用原因", d["reason"]), ("适用边界", d["limitations"])],
            refs=[("官方产品资料", d["url"])],
            field="disclosures",
        )
    deck.prose_pages(
        "方法与解释边界",
        [
            ("行情与事件", "复权日线、公司行动、来源日期与数据快照固定本次复核范围。日线无法分离盘中反应。"),
            ("关联评级", "相对基准反应按事前波动标准化。高反应与高证据可信度不同，均不能证明因果。"),
            (
                "回测与宏观",
                "压力月份为全样本事后选择，宏观采用当前历史版本。二者仅用于解释，不进入交易信号。",
            ),
            *[("数据限制", warning) for warning in bundle.warnings],
        ],
        field="methodology / warnings",
    )
    refs = [(s.title, s.url) for s in bundle.sources]
    refs += [(f"行情 {sym}", d.source_url) for sym, d in bundle.datasets.items()]
    for start in range(0, len(refs), 6):
        group = refs[start : start + 6]
        s = deck.page("原始来源索引", "点击标题打开原文；数据快照哈希保存在各页演讲者备注。", refs=group)
        for i, (title, url) in enumerate(group):
            deck.text(s, f"{start + i + 1:02}", 0.667, 2.22 + i * 0.66, 0.5, 0.35, 16, "muted", numeric=True)
            label = "\n".join(_wrap(title, 10.9, 15)[:2])
            deck.text(s, label, 1.4, 2.22 + i * 0.66, 11, 0.59, 15, "accent", url=url)
            s.notes_slide.notes_text_frame.text += f"\n完整来源标题：{title}\n{url}"
    deck.prs.save(target)
