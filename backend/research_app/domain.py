import json
import math
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .research_contract import ResearchAssessment


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False)
    return sha256(body.encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchSpec(Contract):
    intent: Literal["event_study", "asset_comparison", "combined"]
    title: str = Field(min_length=1, max_length=180)
    symbols: list[str] = Field(min_length=1, max_length=5)
    start: date
    end: date
    topics: list[str] = Field(default_factory=list, max_length=10)
    required_events: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确点名必须覆盖的事件或主题，逐项保留原意；不添加推测要求",
    )
    event_scope: Literal["broad", "focused"] = "broad"
    benchmark: str = "SPY"
    windows: list[int] = Field(default_factory=lambda: [1, 5, 20])
    weights: list[float] = Field(default_factory=list)
    rebalance_months: Literal[0, 1, 3, 12] = 1
    cost_bps: float = Field(default=10, ge=0, le=100)
    initial_capital: float = Field(default=100000, gt=0, le=1e12)
    outputs: list[Literal["html", "xlsx", "pptx", "docx"]] = Field(
        default_factory=lambda: ["html"],
        description="本次请求的产物集合，不是可用格式列表。报告默认html；文档docx；底稿xlsx；汇报pptx；不导出为空。",
    )
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("symbols", mode="before")
    @classmethod
    def symbol_syntax(cls, values: list[str]) -> list[str]:
        import re

        if not isinstance(values, list) or any(not isinstance(s, str) for s in values):
            raise ValueError("资产代码必须是字符串列表")
        result = list(dict.fromkeys(s.strip().upper() for s in values))
        if any(not re.fullmatch(r"[A-Z0-9.^=-]{1,20}", s) for s in result):
            raise ValueError("资产代码格式无效")
        return result

    @field_validator("benchmark")
    @classmethod
    def benchmark_syntax(cls, value: str) -> str:
        return cls.symbol_syntax([value])[0]

    @model_validator(mode="after")
    def valid_spec(self) -> "ResearchSpec":
        if self.end <= self.start or (self.end - self.start).days > 365 * 20:
            raise ValueError("研究区间应大于一天且不超过二十年")
        if self.end > datetime.now(timezone.utc).date():
            raise ValueError("研究截止日期不能在未来")
        if self.intent != "event_study" and len(self.symbols) < 2:
            raise ValueError("比较研究需要至少两个资产")
        if not self.weights:
            self.weights = [1 / len(self.symbols)] * len(self.symbols)
        if len(self.weights) != len(self.symbols) or any(not math.isfinite(w) or w < 0 for w in self.weights):
            raise ValueError("权重必须非负且与资产数量相符")
        if abs(sum(self.weights) - 1) > 1e-8:
            raise ValueError("权重合计必须为 100%")
        if not self.windows or any(w < 1 or w > 90 for w in self.windows):
            raise ValueError("事件窗口必须为 1–90 个交易日")
        self.windows = sorted(set(self.windows))
        self.outputs = list(dict.fromkeys(self.outputs))
        return self


class Instrument(Contract):
    symbol: str
    name: str
    currency: str
    asset_type: str
    timezone: str
    calendar: str
    source_url: str
    proxy_note: str | None = None


class Bar(Contract):
    date: str
    opened_at: str
    closed_at: str
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float

    @model_validator(mode="after")
    def valid_bar(self) -> "Bar":
        prices = [self.open, self.high, self.low, self.close, self.adj_close]
        if any(not math.isfinite(v) or v <= 0 for v in prices):
            raise ValueError("价格必须是有限正数")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC 区间无效")
        if self.volume < 0 or not math.isfinite(self.volume):
            raise ValueError("成交量无效")
        return self


class MarketDataset(Contract):
    id: str
    instrument: Instrument
    provider: str = "Yahoo Finance"
    retrieved_at: str
    source_url: str
    content_hash: str
    price_basis: str = "Yahoo split-adjusted OHLC; adj_close additionally reflects distributions"
    bars: list[Bar]
    corporate_actions: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class SourceRecord(Contract):
    id: str
    title: str
    url: str
    publisher: str
    retrieved_at: str
    published_at: str | None = None
    excerpt: str = ""
    content_hash: str = ""
    status: Literal["retrieved", "metadata_only", "curated_reference", "unavailable"] = "retrieved"


class EventRecord(Contract):
    id: str
    title: str
    date: date
    published_at: str | None = None
    occurred_at: str | None = None
    public_disclosure_at: str | None = None
    disclosure_source_id: str = ""
    disclosure_quote: str = ""
    reported_at: str | None = None
    time_precision: Literal["timestamp", "date", "uncertain"] = "date"
    timing_basis: Literal["announcement", "retrospective"] = Field(
        default="announcement",
        description="announcement 是当时公开的公告；retrospective 是事后报道已经发生的事件/市场反应，不能作为当时可用信号",
    )
    symbols: list[str]
    category: str = "industry"
    summary: str
    source_ids: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"] = "medium"
    uncertainty: str = ""
    date_source_id: str = Field(
        default="", description="支持事件发生日期的已读 source_id，必须也在 source_ids 中"
    )
    date_quote: str = Field(
        default="",
        description="原文中支持该事件日期的逐字短引文；若使用同页发布元数据可留空，不能引用 URL 路径",
    )
    satisfies: list[str] = Field(
        default_factory=list,
        description="本事件直接满足的 required_events 原文；论文公开不能冒充模型首次发布",
    )


class Claim(Contract):
    id: str
    text: str
    kind: Literal["fact", "analysis", "assumption"]
    evidence_ids: list[str]
    metric_ids: list[str] = Field(default_factory=list)


class ResearchBundle(Contract):
    schema_version: str = "1.1"
    method_version: str = "2026.09.4"
    id: str
    created_at: str
    mode: Literal["live", "sample"]
    spec: ResearchSpec
    datasets: dict[str, MarketDataset]
    sources: list[SourceRecord]
    events: list[EventRecord]
    annotations: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    comparison: dict[str, Any]
    claims: list[Claim]
    coverage: list[dict[str, Any]]
    warnings: list[str]
    disclosures: list[dict[str, str]]
    review: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    research: ResearchAssessment | None = None

    @property
    def completion_status(self) -> str:
        if self.research is not None:
            return "complete" if self.research.status == "complete" else "partial"
        comparison_missing = len(self.spec.symbols) > 1 and (
            not self.comparison.get("asset_metrics") or not self.comparison.get("macro", {}).get("CPIAUCNS")
        )
        return (
            "partial"
            if not self.review.get("passed")
            or not self.events
            or comparison_missing
            or not self.quality.get("passed", False)
            else "complete"
        )


GLD_DISCLOSURE = {
    "title": "黄金（GLD ETF 代理）",
    "description": "GLD（SPDR Gold Shares）由实物黄金支持，目标是反映扣除信托费用后的金价表现。"
    "它于 2004 年上市，在 NYSE Arca 以美元交易，参考 LBMA Gold Price PM。",
    "reason": "采用 GLD 是因为其黄金敞口明确、交易历史较长，并具有可复核的美元行情，适合构建可投资代理的比较与回测。",
    "limitations": "ETF 价格与现货金价存在费用、跟踪及交易时段差异。官方披露费用率为 0.40%（2026-09-28 核验）；"
    "历史价格已体现基金费用，回测只另计指定交易成本，避免重复扣费。",
    "url": "https://www.spdrgoldshares.com/usa/gld/",
    "verified_at": "2026-09-28",
}
