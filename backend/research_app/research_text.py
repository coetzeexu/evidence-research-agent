"""Evidence-bound synthesis and publication gate, shared by research and follow-up chat."""

import asyncio
import json
import re
from urllib.parse import urlsplit

from .domain import digest, now_iso
from .research_contract import (
    ClaimVerdict,
    EvidencePassage,
    MeaningCheck,
    MeaningReview,
    NarrativeDraft,
    NarrativePatch,
    NarrativeReview,
    QuestionCoverageReview,
    ResearchAssessment,
    ResearchFinding,
    ResearchGap,
    ResearchQuestion,
    apply_narrative_patch,
)
from .research_coverage import coverage_requirements, question_coverage_errors
from .research_logic import repair_numeric_transcription, verify_relationships
from .research_metrics import display_metric, metric_catalog
from .research_semantics import verify_meaning

# Paired reviewers get one extra call used only after a schema-validation failure:
# a single malformed response must not discard an otherwise reviewable draft.
REVIEW_CALL_LIMIT = 3

TOKEN = re.compile(r"\{\{([^{}\s]+)\}\}")
FINANCIAL_NUMBER = re.compile(
    r"[+-]?\d[\d,.]*\s*(?:%|％|bps\b|亿美元|万美元|美元|亿元|万元|倍)|(?<![\w.])[-+]?\d+\.\d+(?![\w.])", re.I
)
SAMPLE_COUNT = re.compile(r"\d[\d,]*\s*(?:个(?:月(?:度)?(?:观测|样本)?|(?:有效)?(?:观测|样本))|条日线)")


async def paired_reviews(*calls):
    # If one check fails, cancel and await the other before returning partial.
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(call) for call in calls]
    return [task.result() for task in tasks]


def research_questions(spec, extra=None, request=""):
    rows = []

    def add(qid, question, acceptance, kind, required_event=""):
        rows.append(
            ResearchQuestion(
                id=qid,
                question=question,
                acceptance=acceptance,
                kind=kind,
                required_event=required_event,
                priority=1 if required_event else 2,
            )
        )

    add(
        "market",
        "行情数据覆盖到何时、主要收益与风险表现如何？",
        "说明实际起止区间、行情口径及可复核的收益/回撤；比较任务以同口径执行基线为主。",
        "market",
    )
    for i, event in enumerate(spec.required_events):
        add(
            f"required-{i + 1}",
            event,
            "原文核实具体事实与日期；区分发生/公开/报道/反应时间，给出对应窗口、强度与证据局限。",
            "event",
            event,
        )
    if spec.intent in {"event_study", "combined"}:
        add(
            "attribution",
            "主要行情变化与同期信息有什么关系，哪些解释仍无法确认？",
            "讨论已调查的主要异动与时间线，区分反应强度和证据可信度；至少说明竞争性解释与因果边界。",
            "event",
        )
    if len(spec.symbols) > 1:
        add(
            "hedge",
            "这些资产在市场压力期是否提供保护？",
            "使用相同压力月份，区分正收益与相对抗跌；披露事后选样与样本量限制。",
            "hedge",
        )
        add(
            "inflation",
            "这些资产是否保全购买力、是否随通胀变化？",
            "结合实际收益、CPI分组/相关性，区分保值结果与稳定抗通胀机制；明确宏观数据是回顾性的。",
            "inflation",
        )
        add(
            "allocation",
            "组合相对单资产有什么收益与风险代价？",
            "只比较相同执行口径的组合与单资产基线，给出条件化配置判断和可能推翻判断的证据。",
            "allocation",
        )
        add(
            "sensitivity",
            "配置判断对成本、权重、频率和样本区间是否敏感？",
            "引用已计算的敏感性结果，不推荐事后最优参数，分段不冒充样本外检验。",
            "sensitivity",
        )
    seen_requests = set()
    for question in (extra or [])[:4]:
        item = ResearchQuestion.model_validate(question)
        if len(item.request_quote.strip()) < 4 or item.request_quote not in request:
            continue
        key = " ".join(item.request_quote.split())
        if key in seen_requests:
            continue
        seen_requests.add(key)
        # The model may propose methods, but cannot invent user acceptance criteria.
        item.question = item.request_quote
        item.priority = 1
        item.required = True
        item.acceptance = "逐项回答这段用户原文中的要求，给出证据、计算依据与限制：" + item.request_quote
        item.id = f"custom-{len(seen_requests)}"
        item.status, item.finding_ids, item.gaps = "pending", [], []
        rows.append(item)
    return rows


def finding_text(finding):
    return "\n".join(
        [finding.title, finding.text, finding.counterevidence, finding.limitations, finding.changes_if]
    )


def numeric_refs(finding):
    return list(dict.fromkeys(TOKEN.findall(finding_text(finding))))


def normalize_metric_tokens(draft, metrics):
    """Repair a literal protocol prefix only when the exact referenced metric exists."""
    changes = []
    for finding in draft.findings:
        for field in ("title", "text", "counterevidence", "limitations", "changes_if"):

            def replace(match):
                supplied = match[1]
                canonical = supplied.removeprefix("metric_id:")
                if supplied != canonical and canonical in metrics:
                    changes.append(
                        {"finding_id": finding.id, "field": field, "from": supplied, "to": canonical}
                    )
                    return "{{" + canonical + "}}"
                return match[0]

            setattr(finding, field, TOKEN.sub(replace, getattr(finding, field)))
    return changes


def origin_groups(sources, texts):
    """Conservative grouping; different URLs are never asserted to be independent sources."""
    groups = {}
    for source in sources:
        body = " ".join(texts.get(source.id, "").lower().split())
        agency = next(
            (agency for agency in ["reuters", "associated press", "afp"] if agency in body[:3000]), None
        )
        groups[source.id] = f"wire:{agency}" if agency else f"publisher:{urlsplit(source.url).hostname}"
    fingerprints = {}
    for source in sources:
        body = texts.get(source.id, "")
        if body:
            fingerprint = digest(" ".join(body.split()))
            groups[source.id] = fingerprints.setdefault(fingerprint, groups[source.id])
    return groups


def validate_draft(draft, bundle, questions, texts, metrics):
    sources = {s.id: s for s in bundle.sources}
    question_ids = {q.id for q in questions}
    data_ids = set(sources) | {d.id for d in bundle.datasets.values()}
    source_groups = origin_groups(bundle.sources, texts)
    errors, passages, seen = {}, [], set()
    for finding in draft.findings:
        issues = []
        if finding.id in seen:
            issues.append("结论 ID 重复")
        seen.add(finding.id)
        if not set(finding.question_ids).issubset(question_ids):
            issues.append("引用了不存在的研究问题")
        mids = numeric_refs(finding)
        if any(mid not in metrics for mid in mids):
            issues.append("数值引用不存在，不能补造或心算")
        if any(set(metrics[mid].dataset_ids) - data_ids for mid in mids if mid in metrics):
            issues.append("指标依赖的行情或宏观来源缺失")
        plain = TOKEN.sub("", finding_text(finding))
        for field in ["title", "text", "counterevidence", "limitations", "changes_if"]:
            field_text = getattr(finding, field)
            for token in TOKEN.finditer(field_text):
                metric = metrics.get(token[1])
                suffix = field_text[token.end() :].lstrip()
                if metric and re.match(r"[%％]|百分比|bps\b|美元", suffix, re.I):
                    issues.append(f"{field} 指标 {metric.id} 后重复或错配单位；单位由指标契约格式化")
            plain_field = TOKEN.sub("", getattr(finding, field))
            plain_field = re.sub(r"\b[A-Za-z][\w-]*-\d+(?:\.\d+)+\b", "", plain_field)
            plain_field = re.sub(r"(?i)arxiv[:\s]*\d{4}\.\d{4,5}(?:v\d+)?", "", plain_field)
            for match in dict.fromkeys(FINANCIAL_NUMBER.findall(plain_field)):
                candidates = []
                number = re.search(r"[+-]?[\d,.]+", match)
                if number:
                    value = float(number[0].replace(",", ""))
                    if "%" in match or "％" in match:
                        candidates = [
                            mid
                            for mid, metric in metrics.items()
                            if metric.unit == "percent" and abs(metric.value - value / 100) < 1e-8
                        ]
                    elif "bps" in match.lower():
                        candidates = [
                            mid
                            for mid, metric in metrics.items()
                            if mid.endswith("cost_bps") and metric.value == value
                        ]
                suggestion = (
                    "可选已计算引用：" + ", ".join("{{" + mid + "}}" for mid in candidates[:8])
                    if candidates
                    else "没有对应指标时省去此数字，保留事实描述并回链原文"
                )
                issues.append(f"{field} 含手写数字「{match}」；{suggestion}")
            for match in dict.fromkeys(SAMPLE_COUNT.findall(plain_field)):
                issues.append(
                    f"{field} 含未绑定的观测/样本数「{match}」；使用对应指标占位符，"
                    "CPI样本数用 inflation.资产.n，估值数用 observations，收益数用 return_observations"
                )
        if "{{" in TOKEN.sub("", finding_text(finding)) or "}}" in TOKEN.sub("", finding_text(finding)):
            issues.append("指标占位符格式错误")
        groups = {metrics[mid].comparison_group for mid in mids if mid in metrics}
        if "execution" in groups and groups.intersection({"daily", "monthly-price"}):
            issues.append("同一结论混用了执行回测与无费用价格回顾；应拆开说明，不可直接比较")
        if re.search(r"(?<!\w)f\d+\b", plain):
            issues.append("正文依赖内部结论编号；每条结论应独立表达并直接绑定依据")
        if not mids and not finding.evidence:
            issues.append("结论缺少原文证据或计算依据")
        if finding.kind != "fact" and not finding.limitations.strip():
            issues.append("推断/假设缺少局限")
        for quote in finding.evidence:
            source, body = sources.get(quote.source_id), texts.get(quote.source_id, "")
            start = body.find(quote.quote)
            if not source or source.status != "retrieved" or start < 0:
                issues.append(f"原文引文不可定位：{quote.source_id}")
                continue
            passages.append(
                EvidencePassage(
                    **quote.model_dump(),
                    id=f"passage-{digest([source.id, start, quote.quote])[:16]}",
                    start=start,
                    end=start + len(quote.quote),
                    content_hash=digest(body),
                    origin_group=source_groups[source.id],
                    published_at=source.published_at,
                )
            )
        if issues:
            errors.setdefault(finding.id, []).extend(issues)
    return errors, list({p.id: p for p in passages}.values())


def accepted_findings(draft, review, errors):
    verdicts = {}
    for verdict in review.claims:
        verdicts.setdefault(verdict.finding_id, []).append(verdict)
    return [
        f
        for f in draft.findings
        if f.id not in errors
        and len(verdicts.get(f.id, [])) == 1
        and verdicts[f.id][0].verdict == "supported"
    ]


def gap_id(gap):
    return "gap-" + digest([gap.question_id, gap.reason])[:16]


def unresolved_gaps(draft, review, accepted):
    """Disclosure is not completion; only an explicit, located resolution closes a gap."""
    findings = {f.id: f for f in accepted}
    unresolved = []
    for gap in {gap_id(g): g for g in draft.gaps}.values():
        resolutions = [
            r
            for q in review.questions
            if q.question_id == gap.question_id and q.answered
            for r in q.resolved_gaps
            if r.gap_id == gap_id(gap)
        ]
        if not any(
            r.finding_id in findings
            and gap.question_id in findings[r.finding_id].question_ids
            and r.quote in finding_text(findings[r.finding_id])
            for r in resolutions
        ):
            unresolved.append(gap)
    return unresolved


def render_research(assessment, bundle):
    catalogue = {m.id: m for m in assessment.metrics}

    def fill(text):
        value = TOKEN.sub(lambda m: display_metric(catalogue[m[1]]), text).replace("美元 美元", "美元")
        return re.sub(r"\bbps\s*bps\b", "bps", value)

    parts = [
        f"{bundle.spec.title}\n\n研究状态：{'完整' if assessment.status == 'complete' else '部分完成'}。"
        f"请求区间：{bundle.spec.start} 至 {bundle.spec.end}；实际数值区间见各指标口径。"
    ]
    used_sources, used_groups = [], {}
    for finding in assessment.findings:
        mids = numeric_refs(finding)
        refs = list(
            dict.fromkeys(
                [q.source_id for q in finding.evidence]
                + [sid for mid in mids for sid in catalogue[mid].dataset_ids]
            )
        )
        used_sources.extend(refs)
        paragraphs = [f"**{fill(finding.title)}**", fill(finding.text)]
        for label, text in [
            ("竞争性解释", finding.counterevidence),
            ("局限", finding.limitations),
            ("改变判断的条件", finding.changes_if),
        ]:
            if text:
                paragraphs.append(f"{label}：{fill(text)}")
        paragraphs.append("依据：" + " ".join(f"[{sid}]" for sid in refs))
        parts.append("\n\n".join(paragraphs))
        for mid in mids:
            metric = catalogue[mid]
            key = (metric.start, metric.end, metric.frequency, metric.method)
            used_groups[key] = True
    if assessment.gaps:
        parts.append(
            "**尚未解决的问题**\n\n"
            + "\n".join(
                f"- {g.reason}" + (f"；下一步：{g.next_action}" if g.next_action else "")
                for g in assessment.gaps
            )
        )
    parts.append(
        "**计算口径**\n\n"
        + "\n".join(
            f"- {start} 至 {end}；{frequency}；{method}。" for start, end, frequency, method in used_groups
        )
    )
    links = {s.id: (s.title, s.url) for s in bundle.sources}
    links.update({d.id: (f"{symbol} 行情", d.source_url) for symbol, d in bundle.datasets.items()})
    parts.append(
        "**来源**\n\n"
        + "\n".join(
            f"- [{sid}] {links[sid][0]}：{links[sid][1]}"
            for sid in dict.fromkeys(used_sources)
            if sid in links
        )
    )
    return "\n\n".join(parts)


class NarrativeService:
    def __init__(self, runtime, budget=None, scope="research", allow_retrieval=False):
        self.runtime = runtime
        self.budget = budget or runtime.budget
        self.scope = scope
        self.allow_retrieval = allow_retrieval

    async def compose(self, bundle, questions, request="", history=None, selected=None):
        runtime = self.runtime
        # Completion belongs to an accepted assessment, never to a carried-over question list.
        questions = [
            q.model_copy(update={"status": "pending", "finding_ids": [], "gaps": []}, deep=True)
            for q in questions
        ]
        metrics = metric_catalog(bundle)
        context = {
            "verification_version": "1.5",
            "verification_prompts": {
                name: digest(body) for name, body in getattr(runtime, "prompts", {}).items()
            },
            "request": request,
            "spec": bundle.spec.model_dump(mode="json"),
            "selected_id": selected,
            "questions": [q.model_dump(exclude={"status", "gaps", "finding_ids"}) for q in questions],
            "coverage_requirements": {q.id: coverage_requirements(q) for q in questions},
            "metric_catalog": [m.model_dump() for m in metrics.values()],
            "events": [e.model_dump(mode="json") for e in bundle.events],
            "annotations": bundle.annotations,
            "major_moves": sorted(bundle.changes, key=lambda c: c.get("strength", 0), reverse=True)[:5],
            "coverage": bundle.quality,
            "warnings": bundle.warnings,
            "disclosures": bundle.disclosures,
            "datasets": [d.model_dump(exclude={"bars"}) for d in bundle.datasets.values()],
            "sensitivity_scenarios": [
                {
                    "id": f"sensitivity.{i}",
                    "dimension": row["dimension"],
                    "label": row["label"],
                    "start": row["start"],
                    "end": row["end"],
                }
                for i, row in enumerate(bundle.comparison.get("sensitivity", {}).get("rows", []))
            ],
            "evidence": [
                {"source": s.model_dump(), "untrusted_text": runtime.texts.get(s.id, "")}
                for s in bundle.sources
                if runtime.texts.get(s.id)
            ],
            "history": (history or [])[-12:],
        }
        if bundle.spec.intent == "asset_comparison" and self.scope == "research":
            context["metric_catalog"] = [
                m
                for m in context["metric_catalog"]
                if m["comparison_group"] not in {"daily", "monthly-price", "event"}
            ]
            context["annotations"], context["major_moves"] = [], []
        input_hash = digest(context)
        counter_path = runtime.root / f"{self.scope}-text-attempts.json"
        state = (
            json.loads(counter_path.read_text()) if counter_path.exists() else {"attempts": 0, "audits": []}
        )
        best = ResearchAssessment(questions=questions, metrics=list(metrics.values()), input_hash=input_hash)
        saved_path = runtime.root / f"{self.scope}-assessment.json"
        if saved_path.exists():
            saved = ResearchAssessment.model_validate_json(saved_path.read_text())
            if saved.input_hash == input_hash:
                best = saved
        repair = state.get("last_repair", {})
        if repair and state.get("input_hash") != input_hash:
            failed = {
                f["id"]: f for f in [*repair.get("retained_findings", []), *repair.get("replace_only", [])]
            }
            repair.update(
                replace_only=list(failed.values()), retained=[], retained_findings=[], certificates={}
            )
        state["input_hash"] = input_hash
        while state["attempts"] < 3 and self.budget.remaining > 2:
            state["attempts"] += 1
            runtime.store.save_json(counter_path, state)
            runtime.store.emit(
                runtime.run_id,
                "step",
                "综合研究结论" if state["attempts"] == 1 else "修复正文证据问题",
                phase="synthesis",
            )
            try:
                if repair and "retained" in repair:
                    retained_ids = {f["id"] for f in repair["retained"]}
                    patch_context = {**context, "repair": repair}
                    for patch_attempt in range(2):
                        patch = await runtime.structured(
                            "text-repair", NarrativePatch, patch_context, budget=self.budget, limit=2
                        )
                        try:
                            draft = apply_narrative_patch(
                                [ResearchFinding.model_validate(f) for f in repair["retained_findings"]]
                                if "retained_findings" in repair
                                else [f for f in best.findings if f.id in retained_ids],
                                [ResearchFinding.model_validate(f) for f in repair["replace_only"]],
                                patch,
                                [ResearchGap.model_validate(g) for g in repair.get("unresolved_gaps", [])],
                            )
                            break
                        except ValueError as exc:
                            runtime.store.save_json(
                                runtime.root
                                / f"{self.scope}-invalid-patch-{state['attempts']}-{patch_attempt}.json",
                                {"patch": patch.model_dump(), "error": str(exc)},
                            )
                            if patch_attempt:
                                raise
                            patch_context = {
                                **patch_context,
                                "rejected_patch": patch.model_dump(),
                                "patch_validation_error": str(exc),
                            }
                    runtime.store.save_json(
                        runtime.root / f"{self.scope}-patch-{state['attempts']}.json", patch.model_dump()
                    )
                else:
                    draft = await runtime.structured(
                        "synthesis", NarrativeDraft, context, budget=self.budget, limit=2
                    )
                token_repairs = normalize_metric_tokens(draft, metrics)
                errors, passages = validate_draft(draft, bundle, questions, runtime.texts, metrics)
                local_repair_needed = bool(errors)
                certificates = repair.get("certificates", {})
                certified = {
                    f.id: ClaimVerdict.model_validate(certificates[f.id]["verdict"])
                    for f in draft.findings
                    if f.id in certificates
                    and certificates[f.id]["hash"] == digest(f.model_dump())
                    and certificates[f.id].get("meaning")
                }
                review_draft = NarrativeDraft(findings=[f for f in draft.findings if f.id not in certified])
                runtime.store.emit(runtime.run_id, "step", "逐条核验最终正文", phase="text_review")
                referenced = {e.source_id for f in draft.findings for e in f.evidence}
                referenced_metrics = {m for f in draft.findings for m in numeric_refs(f)}
                families = {mid.rsplit(".", 1)[0] for mid in referenced_metrics}
                review_context = {
                    k: v
                    for k, v in context.items()
                    if k not in {"evidence", "history", "metric_catalog", "annotations", "major_moves"}
                }
                review_context["evidence"] = [
                    s for s in context["evidence"] if s["source"]["id"] in referenced
                ]
                review_context["metric_catalog"] = [
                    m.model_dump()
                    for mid, m in metrics.items()
                    if mid.rsplit(".", 1)[0] in families
                    or (
                        mid.startswith("execution.")
                        and any(m.startswith("execution.") for m in referenced_metrics)
                    )
                    or (
                        mid.startswith("stress-month.")
                        and any(m.startswith("stress.") for m in referenced_metrics)
                    )
                ]
                review_context["stress_periods"] = bundle.comparison.get("stress_periods", [])
                review_context["previous_numeric_check"] = repair.get("numeric_check", [])
                review_context["previous_program_findings"] = repair.get("deterministic_errors", {})
                review_context["verified_findings"] = [
                    f.model_dump() for f in draft.findings if f.id in certified
                ]
                review_context["open_gaps"] = [{"id": gap_id(g), **g.model_dump()} for g in draft.gaps]
                review, meaning = await paired_reviews(
                    runtime.structured(
                        "text-reviewer",
                        NarrativeReview,
                        {
                            **review_context,
                            "draft": review_draft.model_dump(),
                            "deterministic_findings": errors,
                        },
                        budget=self.budget,
                        limit=REVIEW_CALL_LIMIT,
                    ),
                    runtime.structured(
                        "meaning-review",
                        MeaningReview,
                        {
                            "draft": review_draft.model_dump(),
                            "verified_findings": review_context["verified_findings"],
                            "spec": context["spec"],
                            "evidence": review_context["evidence"],
                            "metric_catalog": review_context["metric_catalog"],
                            "datasets": context["datasets"],
                            "methods": sorted({m["method"] for m in review_context["metric_catalog"]}),
                        },
                        budget=self.budget,
                        limit=REVIEW_CALL_LIMIT,
                    ),
                )
                # Same source/metric snapshot and exact finding hash permit certificate reuse.
                # A new substantive objection still revokes that certificate; never downgrade by ID.
                objections = {v.finding_id for v in review.claims if v.verdict != "supported"}
                objections.update(c.finding_id for c in meaning.checks if c.violations)
                if objections.intersection(certified):
                    best = ResearchAssessment(
                        questions=questions, metrics=list(metrics.values()), input_hash=input_hash
                    )
                review.claims = [
                    v for v in review.claims if v.finding_id not in certified or v.finding_id in objections
                ] + [v for fid, v in certified.items() if fid not in objections]
                meaning.checks = [
                    c for c in meaning.checks if c.finding_id not in certified or c.finding_id in objections
                ] + [
                    MeaningCheck.model_validate(certificates[fid]["meaning"])
                    for fid in certified
                    if fid not in objections
                ]
                for fid, problems in verify_meaning(draft, meaning).items():
                    errors.setdefault(fid, []).extend(problems)
                review, transcription_repairs = await repair_numeric_transcription(
                    runtime, draft, review, metrics, self.budget
                )
                relation_errors, relation_checks = verify_relationships(draft, review, metrics)
                local_repair_needed |= (
                    bool(relation_errors)
                    or any(v.repair == "rewrite" for v in review.claims if v.verdict != "supported")
                    or any(v.repair == "rewrite" for c in meaning.checks for v in c.violations)
                )
                for fid, problems in relation_errors.items():
                    errors.setdefault(fid, []).extend(problems)
                eligible = accepted_findings(draft, review, errors)
                runtime.store.emit(runtime.run_id, "step", "核对必答问题与研究边界", phase="text_review")
                coverage = await runtime.structured(
                    "question-review",
                    QuestionCoverageReview,
                    {
                        "request": request,
                        "questions": context["questions"],
                        "coverage_requirements": context["coverage_requirements"],
                        "sensitivity_scenarios": context["sensitivity_scenarios"],
                        "accepted_findings": [f.model_dump() for f in eligible],
                        "open_gaps": review_context["open_gaps"],
                        "available_metric_ids": list(metrics),
                    },
                    budget=self.budget,
                    limit=2,
                )
                source_question_review = [q.model_dump() for q in review.questions]
                review.questions = coverage.questions
            except Exception as exc:
                state["audits"].append({"attempt": state["attempts"], "error_type": type(exc).__name__})
                runtime.store.save_json(counter_path, state)
                break
            accepted = accepted_findings(draft, review, errors)
            accepted_ids = {f.id for f in accepted}
            rejected = [f for f in draft.findings if f.id not in accepted_ids]
            declared_gaps = unresolved_gaps(draft, review, accepted)
            audit = {
                "attempt": state["attempts"],
                "draft_hash": digest(draft.model_dump()),
                "deterministic": errors,
                "review": review.model_dump(),
                "meaning_review": meaning.model_dump(),
                "numeric_relationships": relation_checks,
                "numeric_transcription_repairs": transcription_repairs,
                "metric_token_repairs": token_repairs,
                "source_question_review": source_question_review,
                "local_repair_needed": local_repair_needed,
                "open_gaps": [g.model_dump() for g in declared_gaps],
                "accepted_ids": sorted(accepted_ids),
                "accepted_hashes": {f.id: digest(f.model_dump()) for f in accepted},
                "reused_certificates": sorted(set(certified) - objections),
                "coverage_errors": {},
            }
            state["audits"].append(audit)
            runtime.store.save_json(
                runtime.root / f"{self.scope}-draft-{state['attempts']}.json", draft.model_dump()
            )
            verdicts = {
                v.question_id: v
                for v in review.questions
                if sum(x.question_id == v.question_id for x in review.questions) == 1
            }
            assessed_questions, gaps = [], []
            for original in questions:
                q = original.model_copy(deep=True)
                q.finding_ids = [f.id for f in accepted if q.id in f.question_ids]
                verdict = verdicts.get(q.id)
                is_answered = bool(q.finding_ids and verdict and verdict.answered)
                coverage_errors = question_coverage_errors(q, verdict, accepted, bundle)
                if coverage_errors:
                    is_answered = False
                    audit["coverage_errors"][q.id] = coverage_errors
                open_for_question = [g for g in declared_gaps if g.question_id == q.id]
                if open_for_question:
                    is_answered = False
                # Coverage is assessed using accepted findings only. A rejected
                # optional paragraph cannot veto an otherwise complete answer;
                # missing required facts still fail coverage or keep an open gap.
                if q.required_event and not any(q.required_event in e.satisfies for e in bundle.events):
                    is_answered = False
                if q.kind == "inflation" and not bundle.comparison.get("macro", {}).get("CPIAUCNS"):
                    is_answered = False
                q.status = "answered" if is_answered else "insufficient"
                blocking = [
                    v.reason
                    for v in review.claims
                    if v.verdict != "supported"
                    and any(f.id == v.finding_id and q.id in f.question_ids for f in draft.findings)
                ]
                blocking.extend(
                    problem
                    for f in draft.findings
                    if q.id in f.question_ids
                    for problem in errors.get(f.id, [])
                )
                blocking.extend(g.reason for g in open_for_question)
                blocking.extend(coverage_errors)
                q.gaps = (
                    []
                    if is_answered
                    else [
                        "；".join(blocking)
                        if blocking
                        else verdict.reason
                        if verdict
                        else "问题尚未完成独立核验"
                    ]
                )
                if not is_answered and not any(g.question_id == q.id for g in gaps):
                    gaps.append(
                        ResearchGap(
                            question_id=q.id,
                            reason=f"{q.question}：{q.gaps[0]}",
                            next_action="按该问题补充证据或缩小结论",
                        )
                    )
                assessed_questions.append(q)
            gaps = [
                g
                for g in gaps
                if any(q.id == g.question_id and q.status != "answered" for q in assessed_questions)
            ]
            accepted_passages = {digest(e.model_dump()) for f in accepted for e in f.evidence}
            status = (
                "complete"
                if all(q.status == "answered" for q in assessed_questions if q.required) and not gaps
                else "partial"
            )
            if self.scope == "research" and not bundle.quality.get("passed"):
                status = "partial"
                gaps.append(
                    ResearchGap(
                        question_id="coverage",
                        reason="数据或调查覆盖仍有缺口，见问题清单和 coverage",
                        next_action="补齐明确缺口",
                    )
                )
            candidate = ResearchAssessment(
                status=status if accepted else "failed",
                questions=assessed_questions,
                findings=accepted,
                passages=[
                    p
                    for p in passages
                    if digest({"source_id": p.source_id, "quote": p.quote}) in accepted_passages
                ],
                metrics=list(metrics.values()),
                reviews=state["audits"],
                gaps=gaps,
                assessed_at=now_iso(),
                input_hash=input_hash,
                budget=self.budget.snapshot(),
            )
            candidate.text = render_research(candidate, bundle) if accepted else ""
            candidate_rank = (
                sum(q.status == "answered" for q in candidate.questions),
                len(candidate.findings),
            )
            best_rank = (sum(q.status == "answered" for q in best.questions), len(best.findings))
            newly_declared = {g.question_id for g in declared_gaps} - {g.question_id for g in best.gaps}
            if candidate_rank >= best_rank or candidate.status == "complete" or newly_declared:
                best = candidate
                runtime.store.save_json(saved_path, best.model_dump(mode="json"))
            repair = {
                "replace_only": [f.model_dump() for f in rejected],
                "retained": [
                    {"id": f.id, "title": f.title, "question_ids": f.question_ids} for f in accepted
                ],
                "retained_findings": [f.model_dump() for f in accepted],
                "certificates": {
                    f.id: {
                        "hash": digest(f.model_dump()),
                        "verdict": next(v.model_dump() for v in review.claims if v.finding_id == f.id),
                        "meaning": next(c.model_dump() for c in meaning.checks if c.finding_id == f.id),
                    }
                    for f in accepted
                },
                "unanswered_questions": [
                    q.model_dump() for q in assessed_questions if q.status != "answered"
                ],
                "unresolved_gaps": [g.model_dump() for g in declared_gaps],
                "deterministic_errors": errors,
                "review": review.model_dump(),
                "meaning_review": meaning.model_dump(),
                "numeric_check": [c for c in relation_checks if not c["passed"]],
            }
            state["last_repair"] = repair
            runtime.store.save_json(counter_path, state)
            if candidate.status == "complete":
                break
            if (
                self.allow_retrieval
                and not local_repair_needed
                and state["attempts"] < 3
                and self.budget.can_investigate
                and (
                    any(v.repair == "retrieve" for v in review.claims)
                    or any(v.repair == "retrieve" for c in meaning.checks for v in c.violations)
                    or any(g.next_action for g in declared_gaps)
                )
            ):
                break
        if not best.findings:
            best.status = "failed"
            best.gaps = [
                ResearchGap(question_id=q.id, reason="预算内未获得可发布的已核验正文") for q in questions
            ]
        best.reviews = state["audits"]
        best.budget = self.budget.snapshot()
        runtime.store.save_json(saved_path, best.model_dump(mode="json"))
        return best
