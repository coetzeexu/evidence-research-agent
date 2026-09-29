"""Typed, auditable text research. These contracts contain no hidden model reasoning."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


def review_rows(value, identifier):
    """Normalize only unambiguous singleton/keyed records; item validation stays strict."""
    if not isinstance(value, dict):
        return value
    if identifier in value:
        return [value]
    if value and all(isinstance(row, dict) and row.get(identifier, key) == key for key, row in value.items()):
        return [{identifier: key, **row} for key, row in value.items()]
    return value


class ResearchQuestion(Record):
    id: str
    question: str
    acceptance: str
    kind: Literal["event", "market", "hedge", "inflation", "allocation", "sensitivity", "custom"]
    required: bool = True
    priority: int = Field(
        default=2,
        ge=1,
        le=3,
        description="1=用户明确要求，2=必要研究问题，3=可选探索；不能以低优先级取消必答要求",
    )
    required_event: str = ""
    request_quote: str = Field(
        default="", description="额外问题必须逐字引用用户明确要求，不能自行增加指标或验收条件"
    )
    status: Literal["pending", "answered", "insufficient"] = "pending"
    finding_ids: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class EvidenceQuote(Record):
    source_id: str
    quote: str = Field(
        min_length=12, max_length=1200, description="逐字复制保存原文中的连续片段，不使用省略号拼接"
    )


class EvidencePassage(EvidenceQuote):
    id: str
    start: int
    end: int
    content_hash: str
    origin_group: str
    published_at: str | None = None


class ResearchMetric(Record):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str
    label: str
    value: float
    unit: Literal["percent", "number", "integer", "usd", "bps"]
    start: str
    end: str
    frequency: str
    method: str
    comparison_group: str
    dataset_ids: list[str]
    currency: str = "USD"
    meaning: str = ""

    @model_validator(mode="after")
    def validate_count(self):
        if self.unit == "integer" and (not self.value.is_integer() or self.value < 0):
            raise ValueError("计数指标必须是非负整数，不能通过格式化四舍五入")
        return self


class ResearchFinding(Record):
    id: str
    question_ids: list[str] = Field(min_length=1)
    kind: Literal["fact", "analysis", "assumption"]
    title: str = Field(max_length=100)
    text: str = Field(
        max_length=3000, description="中文结论。计算数值只能使用 {{metric_id}}，不得心算或手写百分比"
    )
    evidence: list[EvidenceQuote] = Field(default_factory=list, max_length=5)
    counterevidence: str = Field(
        default="", max_length=700, description="竞争性解释或相反证据；新增事实也必须有 evidence 支持"
    )
    limitations: str = Field(max_length=700)
    confidence: Literal["high", "medium", "low"] = "medium"
    changes_if: str = Field(default="", max_length=500, description="什么新证据或条件会改变这一判断")


class ResearchGap(Record):
    question_id: str
    reason: str
    next_action: str = ""


class NarrativeDraft(Record):
    findings: list[ResearchFinding] = Field(default_factory=list, max_length=24)
    gaps: list[ResearchGap] = Field(default_factory=list)


class TextEdit(Record):
    finding_id: str
    field: Literal["title", "text", "counterevidence", "limitations", "changes_if"]
    old: str = Field(min_length=1, description="从失败结论该字段逐字复制要替换的连续片段")
    new: str = Field(description="正确替换文本；空字符串表示删除该片段，不能在原错误之后仅追加解释")


class EvidenceEdit(Record):
    finding_id: str
    evidence: list[EvidenceQuote]


class NarrativePatch(Record):
    edits: list[TextEdit] = Field(default_factory=list)
    evidence_edits: list[EvidenceEdit] = Field(default_factory=list)
    remove_ids: list[str] = Field(default_factory=list)
    additions: list[ResearchFinding] = Field(default_factory=list, max_length=12)
    gaps: list[ResearchGap] = Field(default_factory=list, description="新增缺口；空列表不能关闭旧缺口")


def apply_narrative_patch(retained, rejected, patch, previous_gaps=()):
    """Edits are scoped to rejected findings. Every patched finding is reviewed again."""
    failures = {f.id: f.model_copy(deep=True) for f in rejected}
    if not set(patch.remove_ids).issubset(failures):
        raise ValueError("修复不能删除已核验结论或未知 ID")
    for edit in patch.edits:
        if edit.finding_id not in failures:
            raise ValueError("修复不能修改已核验结论或未知 ID")
        finding = failures[edit.finding_id]
        old = getattr(finding, edit.field)
        if edit.old not in old:
            raise ValueError("替换必须匹配失败结论原文")
        # An idempotent edit changes nothing and grants no certificate. Do not
        # discard valid sibling edits; all rejected findings are reviewed again.
        if edit.old == edit.new:
            continue
        setattr(finding, edit.field, old.replace(edit.old, edit.new))
    for edit in patch.evidence_edits:
        if edit.finding_id not in failures:
            raise ValueError("证据修复目标不属于失败结论")
        failures[edit.finding_id].evidence = edit.evidence
    ids = {f.id for f in retained} | set(failures)
    if any(f.id in ids for f in patch.additions):
        raise ValueError("新增结论不得覆盖已有结论")
    return NarrativeDraft(
        findings=[
            *retained,
            *[f for fid, f in failures.items() if fid not in patch.remove_ids],
            *patch.additions,
        ],
        gaps=[*previous_gaps, *patch.gaps],
    )


NumericRelation = Literal[
    "not_monotonic",
    "majority",
    "not_majority",
    "abs_gt",
    "abs_lt",
    "abs_increasing",
    "abs_decreasing",
    "increasing",
    "decreasing",
    "gt",
    "ge",
    "lt",
    "le",
    "eq",
    "between",
    "not_between",
    "positive",
    "negative",
    "nonnegative",
    "nonpositive",
    "same_sign",
    "opposite_sign",
]


class NumericAssertion(Record):
    quote: str = Field(
        min_length=2,
        max_length=3000,
        description="逐字复制最短的连续比较短句（主语+关系即可）；不要复制整段数字，不用省略号，不合并不同维度",
    )
    relation: NumericRelation
    metric_ids: list[str] = Field(
        min_length=1,
        max_length=12,
        description="按断言语义绑定指标。increasing/decreasing: 按原文序列相邻值逐一上升/下降，不排序。gt/lt: 第一个与其余逐一比较；between: 第一个是否在后两个之间；positive/negative: 所有值的符号",
    )

    @field_validator("quote")
    @classmethod
    def contiguous_phrase(cls, value):
        if "..." in value or "…" in value:
            raise ValueError("quote 必须是原文最短的连续比较短句，不能用省略号拼接；只复制主语与比较用词即可")
        return value


class ClaimVerdict(Record):
    finding_id: str
    numeric_assertions: list[NumericAssertion] = Field(
        default_factory=list,
        description="先把正文（含反证/局限）中每个重要数值关系逐个翻译成可执行断言，收益和风险分别检查。不填写预期真假，由程序计算。",
    )
    reason: str = Field(
        description="先列可复核依据；若主张实际正确、仅举例未穷举或只是措辞偏好，不能报告事实错误"
    )
    verdict: Literal["supported", "unsupported", "uncertain"]
    repair: Literal["none", "retrieve", "recalculate", "rewrite"] = "none"


class LocatedNumericAssertion(Record):
    span_id: str = Field(description="只能选择程序提供的 spans.id，不重新抄写正文")
    relation: NumericRelation
    metric_ids: list[str] = Field(min_length=1, max_length=12)


class NumericClaimReview(Record):
    finding_id: str
    numeric_assertions: list[LocatedNumericAssertion]


class NumericReview(Record):
    claims: list[NumericClaimReview]

    @field_validator("claims", mode="before")
    @classmethod
    def normalize_rows(cls, value):
        return review_rows(value, "finding_id")


class GapResolution(Record):
    gap_id: str
    finding_id: str
    quote: str = Field(min_length=12, description="逐字引用已回答缺口的结论片段；承认缺失不等于回答")
    reason: str = Field(min_length=10, description="说明依据如何补齐原缺口，不能仅因 answered 为真而关闭")


class QuestionVerdict(Record):
    question_id: str
    reason: str
    answered: bool
    resolved_gaps: list[GapResolution] = Field(default_factory=list)


class NarrativeReview(Record):
    claims: list[ClaimVerdict]
    questions: list[QuestionVerdict]

    @field_validator("claims", "questions", mode="before")
    @classmethod
    def normalize_rows(cls, value, info):
        return review_rows(value, "finding_id" if info.field_name == "claims" else "question_id")


class QuestionCoverageReview(Record):
    questions: list[QuestionVerdict]

    @field_validator("questions", mode="before")
    @classmethod
    def normalize_rows(cls, value):
        return review_rows(value, "question_id")


class MeaningViolation(Record):
    quote: str = Field(min_length=2, description="逐字引用存在实质问题的标题/正文/反证/局限片段")
    reason: str = Field(description="指出证据和结论之间具体缺失的推断环节")
    repair: Literal["retrieve", "recalculate", "rewrite"] = "rewrite"


class MeaningCheck(Record):
    finding_id: str
    inference_audit: str = Field(
        min_length=10,
        description="公开的核验依据：逐项说明属性/因果/机制/外推结论是否由本次证据与研究设计支持，不能只说数字正确",
    )
    violations: list[MeaningViolation]


class MeaningReview(Record):
    checks: list[MeaningCheck]

    @field_validator("checks", mode="before")
    @classmethod
    def normalize_rows(cls, value):
        return review_rows(value, "finding_id")


class ResearchAssessment(Record):
    version: str = "1.0"
    status: Literal["unassessed", "complete", "partial", "failed"] = "unassessed"
    questions: list[ResearchQuestion] = Field(default_factory=list)
    findings: list[ResearchFinding] = Field(default_factory=list)
    passages: list[EvidencePassage] = Field(default_factory=list)
    metrics: list[ResearchMetric] = Field(default_factory=list)
    reviews: list[dict] = Field(default_factory=list)
    gaps: list[ResearchGap] = Field(default_factory=list)
    text: str = ""
    assessed_at: str | None = None
    input_hash: str = ""
    budget: dict = Field(default_factory=dict)
