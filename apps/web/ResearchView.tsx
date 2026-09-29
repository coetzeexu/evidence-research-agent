import { useEffect, useMemo, useState } from 'react';
import {
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  Download,
  FileText,
  Info,
  Search,
  X,
} from 'lucide-react';
import { Chart } from './ChartLoader';
import { QualityPanel } from './QualityPanel';
import { SensitivityPanel } from './SensitivityPanel';
import type { Bundle, Event, Spec } from './types';
import { pct, safeUrl } from './types';
import {
  candleOption,
  comparisonOption,
  heatmapOption,
  portfolioOption,
  reactionStyle,
} from '../../packages/charts/options.mjs';

const confidence: Record<string, string> = { high: '高可信', medium: '中可信', low: '低可信' };
const money = (value: number) =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);

function ReactionBadge({ rating }: { rating: string }) {
  const style = reactionStyle(rating);
  return (
    <span className="reaction-badge" style={{ color: style.color, background: style.tint }}>
      <i style={{ background: style.color }} />
      {rating === '不可评估' ? rating : `${rating}反应`}
    </span>
  );
}

export function Disclosure({ bundle }: { bundle: Bundle }) {
  return (
    <>
      {bundle.disclosures.map((item) => (
        <details className="disclosure" key={item.title} open>
          <summary>
            <Info size={15} />
            <strong>{item.title}</strong>
            <span>产品说明与采用原因</span>
            <ChevronDown size={14} />
          </summary>
          <div>
            <p>
              {item.description} {item.reason}
            </p>
            <p className="muted">{item.limitations}</p>
            <a href={safeUrl(item.url)} target="_blank" rel="noopener noreferrer">
              GLD 官方资料 <ArrowUpRight size={12} />
            </a>
          </div>
        </details>
      ))}
    </>
  );
}

export function EvidencePanel({
  bundle,
  eventId,
  onClose,
}: {
  bundle: Bundle;
  eventId: string;
  onClose: () => void;
}) {
  const event = bundle.events.find((e) => e.id === eventId);
  if (!event) return null;
  const annotations = bundle.annotations.filter((a) => a.event_id === eventId);
  const sources = bundle.sources.filter((s) => event.source_ids.includes(s.id));
  return (
    <div className="evidence-panel">
      <div className="panel-heading">
        <span>
          <BookOpen size={16} /> 证据详情
        </span>
        <button className="icon-button" onClick={onClose} aria-label="关闭证据">
          <X size={16} />
        </button>
      </div>
      <div className="evidence-content">
        <div className="eyebrow">
          {event.date} · {event.category}
        </div>
        <h2>{event.title}</h2>
        <p>{event.summary}</p>
        {bundle.changes
          .filter((c) => c.event_ids.includes(event.id))
          .map((c) => (
            <p className="small muted" key={c.id}>
              {c.date} · {c.type} ·
              {c.associations?.find((a) => a.event_id === event.id)?.reason ||
                '同期候选关联，未证明因果。'}
            </p>
          ))}
        <div className="tag-row">
          <span className="tag green">{confidence[event.confidence]}</span>
        </div>
        {annotations.map((annotation) => (
          <div key={annotation.id}>
            <div className="section-label">
              <span>
                {annotation.symbol} · 相对 {bundle.spec.benchmark}
              </span>
              <ReactionBadge rating={annotation.rating} />
            </div>
            <table className="compact-table">
              <thead>
                <tr>
                  <th>窗口</th>
                  <th>收益</th>
                  <th>相对收益</th>
                </tr>
              </thead>
              <tbody>
                {annotation.windows.map((w) => (
                  <tr key={w.days}>
                    <td>
                      <details>
                        <summary>{w.days} 根日线</summary>
                        <small>
                          UTC 收盘时刻
                          <br />
                          {w.start_closed_at ?? '—'}
                          <br />→ {w.end_closed_at ?? '未满'}
                        </small>
                      </details>
                    </td>
                    <td>{w.complete ? pct(w.return) : '未满'}</td>
                    <td>{pct(w.relative_return)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="small muted">
              方向：{annotation.direction} · 评级窗口：{annotation.direction_window_days ?? '未满'}{' '}
              根日线。
              {annotation.uncertainty} 方向优先采用完整的 5
              日相对表现。加密资产按日历日计，股票按交易日计。
            </p>
          </div>
        ))}
        <div className="section-label">
          原始来源 <span>{sources.length}</span>
        </div>
        {sources.map((source, i) => (
          <a
            key={source.id}
            className="source-card"
            href={safeUrl(source.url)}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span className="source-number">{i + 1}</span>
            <div>
              <strong>{source.title}</strong>
              <small>
                {source.publisher} <ArrowUpRight size={11} />
              </small>
              <p>{source.excerpt}</p>
            </div>
          </a>
        ))}
        <div className="provenance-note">
          <Check size={13} />
          <span>原文与引用均保留稳定 ID，可在数据页复核。关联等级不代表因果概率。</span>
        </div>
      </div>
    </div>
  );
}

function MetricStrip({ bundle, symbol }: { bundle: Bundle; symbol: string }) {
  const metric = bundle.metrics.find((m) => m.id === `performance-${symbol}`);
  const bars = bundle.datasets[symbol].bars.filter(
    (b) => b.date >= bundle.spec.start && b.date <= bundle.spec.end,
  );
  const last = bars.at(-1);
  return (
    <div className="metric-strip">
      <div>
        <span>最新完整收盘</span>
        <strong>
          ${last?.close.toFixed(2)}
          <small>{last?.date}</small>
        </strong>
      </div>
      <div>
        <span>区间累计收益</span>
        <strong className={(metric?.total_return ?? 0) >= 0 ? 'positive' : 'negative'}>
          {pct(metric?.total_return)}
        </strong>
      </div>
      <div>
        <span>最大回撤</span>
        <strong>{pct(metric?.max_drawdown)}</strong>
      </div>
      <div>
        <span>已核验事件</span>
        <strong>
          {bundle.events.filter((e) => e.symbols.includes(symbol)).length}
          <small>条来源关联</small>
        </strong>
      </div>
    </div>
  );
}

function EventsTable({
  events,
  bundle,
  onSelect,
  symbol,
}: {
  events: Event[];
  bundle: Bundle;
  onSelect: (id: string) => void;
  symbol: string;
}) {
  const [query, setQuery] = useState('');
  const filtered = events.filter((e) =>
    (e.title + e.summary).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <section className="surface event-table">
      <div className="surface-title">
        <div>
          <h3>事件与市场反应</h3>
          <span>{events.length} 条事件 · 点击查看证据</span>
        </div>
        <label className="table-search">
          <Search size={14} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索事件"
            aria-label="搜索事件"
          />
        </label>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>事件</th>
              <th>市场反应</th>
              <th>5 日相对收益</th>
              <th>关联可信度</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((event) => {
              const a = bundle.annotations.find(
                (a) => a.event_id === event.id && a.symbol === symbol,
              );
              const w = a?.windows.find((w) => w.days === 5);
              return (
                <tr key={event.id} onClick={() => onSelect(event.id)}>
                  <td className="mono nowrap">{event.date}</td>
                  <td>
                    <button className="event-link" onClick={() => onSelect(event.id)}>
                      {event.title}
                      <ArrowUpRight size={12} />
                    </button>
                    <small className="muted">
                      {event.symbols.join(' · ')} · {event.source_ids.length} 个来源
                    </small>
                  </td>
                  <td>
                    <ReactionBadge rating={a?.rating ?? '不可评估'} />
                    <small className="reaction-direction">{a?.direction ?? '—'} · 相对基准</small>
                  </td>
                  <td className={(w?.relative_return ?? 0) >= 0 ? 'positive' : 'negative'}>
                    {pct(w?.relative_return)}
                  </td>
                  <td>
                    <span className="confidence-dot" />
                    {confidence[a?.confidence ?? event.confidence]}
                  </td>
                </tr>
              );
            })}
            {!filtered.length && (
              <tr>
                <td colSpan={5} className="empty-cell">
                  当前筛选没有已核验事件。未解释行情仍保留在图中。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DataView({ bundle }: { bundle: Bundle }) {
  const [symbol, setSymbol] = useState(bundle.spec.symbols[0]);
  const [page, setPage] = useState(0);
  const ds = bundle.datasets[symbol];
  const bars = ds.bars.filter((b) => b.date >= bundle.spec.start && b.date <= bundle.spec.end);
  function download() {
    const csv = [
      'date,open,high,low,close,adj_close,volume,closed_at',
      ...bars.map((b) =>
        [b.date, b.open, b.high, b.low, b.close, b.adj_close, b.volume, b.closed_at].join(','),
      ),
    ].join('\n');
    const href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = href;
    a.download = `${symbol}-daily.csv`;
    a.click();
    URL.revokeObjectURL(href);
  }
  return (
    <>
      <section className="surface">
        <div className="surface-title">
          <div>
            <h3>行情底稿</h3>
            <span>OHLC 为提供商拆股调整口径，adj_close 另含分配调整</span>
          </div>
          <div className="actions">
            <select
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value);
                setPage(0);
              }}
              aria-label="底稿标的"
            >
              {Object.keys(bundle.datasets).map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <button className="button secondary" onClick={download}>
              <Download size={14} /> CSV
            </button>
          </div>
        </div>
        <div className="table-scroll">
          <table className="numeric">
            <thead>
              <tr>
                {['日期', '开盘', '最高', '最低', '收盘', '复权收盘', '成交量'].map((v) => (
                  <th key={v}>{v}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bars.slice(page * 30, page * 30 + 30).map((b) => (
                <tr key={b.date}>
                  <td>{b.date}</td>
                  {[b.open, b.high, b.low, b.close, b.adj_close].map((n, i) => (
                    <td key={i}>{n.toFixed(3)}</td>
                  ))}
                  <td>{money(b.volume)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="table-footer">
          <span>
            {bars.length} 条完整日线 · 采集 {ds.retrieved_at.slice(0, 16).replace('T', ' ')} UTC
          </span>
          <div className="actions">
            <button className="text-button" disabled={!page} onClick={() => setPage((p) => p - 1)}>
              上一页
            </button>
            <span>
              {page + 1} / {Math.ceil(bars.length / 30)}
            </span>
            <button
              className="text-button"
              disabled={(page + 1) * 30 >= bars.length}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </button>
          </div>
        </div>
        <p className="data-hash">快照 SHA-256 · {ds.content_hash}</p>
      </section>
      <section className="surface">
        <div className="surface-title">
          <div>
            <h3>证据索引</h3>
            <span>原始链接、读取时间和引用片段</span>
          </div>
        </div>
        <div className="sources-grid">
          {bundle.sources.map((s) => (
            <a
              className="source-card"
              href={safeUrl(s.url)}
              key={s.id}
              target="_blank"
              rel="noopener noreferrer"
            >
              <BookOpen size={15} />
              <div>
                <strong>{s.title}</strong>
                <small>
                  {s.publisher} · {s.status}
                </small>
                <p>{s.id}</p>
              </div>
              <ArrowUpRight size={13} />
            </a>
          ))}
        </div>
      </section>
    </>
  );
}

function MethodView({ bundle }: { bundle: Bundle }) {
  return (
    <div className="method-grid">
      <section className="surface prose">
        <h3>方法与适用边界</h3>
        <p>
          事件标注以公开来源和完整日线为依据。市场反应等级衡量相对基准收益与事前波动的关系，关联可信度说明来源和时间匹配程度。两者均不证明因果关系。
        </p>
        <p>
          比较分析采用共同月度估值，并记录各资产实际价格的可用时间。通胀数据使用当前历史版本，只用于事后解释。回测采用固定参数，不通过事后最优组合推断未来收益。
        </p>
        <h4>本次假设</h4>
        <ul>
          {bundle.spec.assumptions.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
        <h4>数据与研究限制</h4>
        <ul>
          {bundle.warnings.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
        <h4>核验记录</h4>
        <p>{bundle.review.summary || '确定性计算与引用检查已执行。'}</p>
        {(bundle.review.findings || []).map((f: any, i: number) => (
          <p key={i}>
            <strong>{f.severity}：</strong>
            {f.issue} {f.repair}
          </p>
        ))}
        <Disclosure bundle={bundle} />
      </section>
      <section className="surface">
        <div className="surface-title">
          <div>
            <h3>检索覆盖</h3>
            <span>{bundle.coverage.length} 次有记录的查询</span>
          </div>
        </div>
        <div className="coverage-list">
          {bundle.coverage.map((r, i) => (
            <div key={i}>
              <span className={`status-dot ${r.status === 'success' ? 'done' : 'warning'}`} />
              <div>
                <strong>{r.query}</strong>
                <small>
                  {r.provider} · {r.start} 至 {r.end} · {r.hits} 条线索
                </small>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function CompareView({ bundle, onRevise }: { bundle: Bundle; onRevise?: (spec: Spec) => void }) {
  const [mode, setMode] = useState('normalized');
  const [view, setView] = useState('performance');
  const [weights, setWeights] = useState(bundle.spec.weights.map((w) => Math.round(w * 100)));
  const [cost, setCost] = useState(bundle.spec.cost_bps);
  const [frequency, setFrequency] = useState(bundle.spec.rebalance_months);
  const option = useMemo(
    () =>
      view === 'correlation'
        ? heatmapOption(bundle)
        : view === 'portfolio'
          ? portfolioOption(bundle)
          : comparisonOption(bundle, mode),
    [bundle, mode, view],
  );
  const valid =
    Math.abs(weights.reduce((a, b) => a + b, 0) - 100) < 0.01 &&
    weights.every((w) => w >= 0) &&
    cost >= 0 &&
    cost <= 100;
  if (bundle.comparison.available === false) {
    return (
      <section className="surface">
        <h3>暂时无法完成月度比较</h3>
        {(bundle.comparison.warnings || []).map((warning: string) => (
          <p key={warning}>{warning}</p>
        ))}
        <p>各资产的行情与来源仍可查看。补齐数据或调整研究区间后可重新计算。</p>
      </section>
    );
  }
  return (
    <>
      <Disclosure bundle={bundle} />
      <SensitivityPanel bundle={bundle} />
      <section className="surface">
        <div className="surface-title">
          <div>
            <h3>资产比较</h3>
            <span>共同完整月份 · 美元计价 · 初始指数 100</span>
          </div>
          <div className="segmented">
            {[
              ['performance', '收益与回撤'],
              ['correlation', '相关性'],
              ['portfolio', '配置回测'],
            ].map(([key, label]) => (
              <button
                key={key}
                className={view === key ? 'active' : ''}
                onClick={() => setView(key)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {view === 'performance' && (
          <div className="chart-subbar">
            <div className="pills">
              {[
                ['normalized', '名义净值'],
                ['real', '实际购买力'],
                ['drawdown', '回撤'],
              ].map(([key, label]) => (
                <button
                  key={key}
                  className={mode === key ? 'active' : ''}
                  onClick={() => setMode(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <span>CPI：当前历史版本，事后分析</span>
          </div>
        )}
        <Chart option={option} height={390} />
        {view === 'portfolio' && (
          <div className="backtest-controls">
            <div className="controls-grid">
              {bundle.spec.symbols.map((symbol, i) => (
                <label key={symbol}>
                  {symbol} 权重 %
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={weights[i]}
                    onChange={(e) =>
                      setWeights((w) => w.map((v, j) => (j === i ? Number(e.target.value) : v)))
                    }
                  />
                </label>
              ))}
              <label>
                成本 bps
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={cost}
                  onChange={(e) => setCost(Number(e.target.value))}
                />
              </label>
              <label>
                再平衡
                <select value={frequency} onChange={(e) => setFrequency(Number(e.target.value))}>
                  <option value={0}>买入持有</option>
                  <option value={1}>每月</option>
                  <option value={3}>每季</option>
                  <option value={12}>每年</option>
                </select>
              </label>
              {onRevise && (
                <button
                  className="button primary"
                  disabled={!valid}
                  onClick={() =>
                    onRevise({
                      ...bundle.spec,
                      weights: weights.map((w) => w / 100),
                      cost_bps: cost,
                      rebalance_months: frequency,
                    })
                  }
                >
                  重算此配置
                </button>
              )}
            </div>
            <p className="small muted">
              {!valid
                ? '权重合计须为 100%，成本须在 0–100 bps 范围。'
                : '实线保留下一开盘执行台账，虚线为 Excel 可重算的月度配置近似。两种口径分别标识。'}
              {!onRevise ? ' 离线报告可查看结果；参数重算可使用 Excel 或运行中的应用。' : ''}
            </p>
          </div>
        )}
      </section>
      <section className="surface">
        <div className="surface-title">
          <div>
            <h3>风险与回报</h3>
            <span>统一月度观测频率，按 12 期年化</span>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>资产</th>
                <th>累计收益</th>
                <th>年化收益</th>
                <th>年化波动</th>
                <th>最大回撤</th>
                <th>样本数</th>
              </tr>
            </thead>
            <tbody>
              {(bundle.comparison.asset_metrics || []).map((m: any) => (
                <tr key={m.symbol}>
                  <td>
                    <strong>{m.symbol}</strong>
                  </td>
                  <td>{pct(m.total_return)}</td>
                  <td>{pct(m.cagr)}</td>
                  <td>{pct(m.volatility)}</td>
                  <td>{pct(m.max_drawdown)}</td>
                  <td>{m.observations} 月</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="surface">
        <div className="surface-title">
          <div>
            <h3>通胀环境与购买力</h3>
            <span>CPI 同比 3% 为预设分组阈值 · 当前历史版本 · 描述性分析</span>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>资产</th>
                <th>高通胀月数</th>
                <th>该组月均收益</th>
                <th>低通胀月数</th>
                <th>该组月均收益</th>
                <th>与 CPI 同比相关性</th>
              </tr>
            </thead>
            <tbody>
              {(bundle.comparison.inflation_summary || []).map((r: any) => (
                <tr key={r.symbol}>
                  <td>
                    <strong>{r.symbol}</strong>
                  </td>
                  <td>{r.high_inflation_n}</td>
                  <td>{pct(r.high_inflation_mean_return)}</td>
                  <td>{r.low_inflation_n}</td>
                  <td>{pct(r.low_inflation_mean_return)}</td>
                  <td>{r.inflation_correlation?.toFixed(2) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="table-footer">
          名义月收益与通胀状态的相关关系不等于保值承诺。请结合上方“实际购买力”曲线和持有期限复核。
        </p>
      </section>
      <section className="surface">
        <div className="surface-title">
          <div>
            <h3>压力期表现</h3>
            <span>事后选取 {bundle.spec.benchmark} 表现最差的月份，供情景复核</span>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>月份</th>
                <th>{bundle.spec.benchmark}</th>
                {bundle.spec.symbols.map((s) => (
                  <th key={s}>{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(bundle.comparison.stress_periods || []).map((r: any) => (
                <tr key={r.date}>
                  <td>{r.date.slice(0, 7)}</td>
                  <td className="negative">{pct(r.benchmark_return)}</td>
                  {bundle.spec.symbols.map((s) => (
                    <td className={r.returns[s] >= 0 ? 'positive' : 'negative'} key={s}>
                      {pct(r.returns[s])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function ResearchView({
  bundle,
  onSelect,
  onRevise,
  artifactBase,
  requestedTab,
}: {
  bundle: Bundle;
  onSelect: (id: string) => void;
  onRevise?: (spec: Spec) => void;
  artifactBase?: string;
  requestedTab?: { tab: string };
}) {
  const [tab, setTab] = useState(bundle.spec.intent === 'asset_comparison' ? 'compare' : 'market');
  const [symbol, setSymbol] = useState(bundle.spec.symbols[0]);
  const [rating, setRating] = useState('');
  useEffect(() => {
    if (requestedTab) setTab(requestedTab.tab);
  }, [requestedTab]);
  const candle = useMemo(() => candleOption(bundle, symbol, { rating }), [bundle, symbol, rating]);
  const tabs = [
    ['market', '行情与事件'],
    ...(bundle.spec.symbols.length > 1 ? [['compare', '比较与回测']] : []),
    ['data', '数据与来源'],
    ['method', '方法与核验'],
    ['artifacts', '研究产物'],
  ];
  return (
    <div className="research-view">
      <div className="research-heading">
        <div>
          <div className="eyebrow">RESEARCH WORKSPACE</div>
          <h1>{bundle.spec.title}</h1>
          <p>
            {bundle.spec.start} <span>—</span> {bundle.spec.end} <span>·</span>{' '}
            {bundle.spec.symbols.join(' / ')} <span>·</span> 基准 {bundle.spec.benchmark}
          </p>
        </div>
        <span className="tag green">
          <Check size={12} />
          {bundle.mode === 'sample' ? '样例回放' : '研究实录'}
        </span>
      </div>
      <nav className="study-tabs" aria-label="研究视图">
        {tabs.map(([key, label]) => (
          <button className={tab === key ? 'active' : ''} key={key} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>
      <div className="study-body">
        <QualityPanel bundle={bundle} onSelect={onSelect} />
        {tab === 'market' && (
          <>
            <section className="surface chart-surface">
              <div className="surface-title">
                <div className="asset-heading">
                  <span className="asset-icon">{symbol.slice(0, 1)}</span>
                  <div>
                    <h3>{symbol}</h3>
                    <span>{bundle.datasets[symbol].instrument.name}</span>
                  </div>
                </div>
                <div className="actions">
                  <select
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                    aria-label="图表标的"
                  >
                    {bundle.spec.symbols.map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                  <select
                    value={rating}
                    onChange={(e) => setRating(e.target.value)}
                    aria-label="市场反应筛选"
                  >
                    <option value="">全部事件</option>
                    <option value="高">高反应</option>
                    <option value="中">中反应</option>
                    <option value="低">低反应</option>
                    <option value="不可评估">不可评估</option>
                  </select>
                  <span className="tag">日线</span>
                </div>
              </div>
              <MetricStrip bundle={bundle} symbol={symbol} />
              <div className="reaction-legend" aria-label="市场反应图例与筛选">
                <strong>事件反应</strong>
                {['', '高', '中', '低', '不可评估'].map((level) => (
                  <button
                    key={level}
                    aria-pressed={rating === level}
                    onClick={() => setRating(level)}
                  >
                    {level && (
                      <i
                        className="reaction-filter-dot"
                        style={{ background: reactionStyle(level).color }}
                        aria-hidden="true"
                      />
                    )}
                    <span>{!level ? '全部' : level === '不可评估' ? level : `${level}反应`}</span>
                    <span className="reaction-filter-count">
                      {
                        bundle.annotations.filter(
                          (a) => a.symbol === symbol && (!level || a.rating === level),
                        ).length
                      }
                    </span>
                  </button>
                ))}
              </div>
              <Chart option={candle} height={440} onEvent={onSelect} />
              <div className="chart-caption">
                <span>橙色「高」 · 蓝色「中」 · 灰色「低」 · 「?」不可评估</span>
                <span>
                  <i className="legend-diamond" /> 待解释变化
                </span>
                <span>K 线绿涨红跌 · 标记颜色表示反应强度</span>
                <span>滚轮缩放 · 点击标记查看证据 · OHLC 为拆股调整口径</span>
              </div>
              <details className="reaction-method">
                <summary>高中低如何判断？</summary>
                <p>
                  用相对基准收益的绝对值，除以历史日波动率 × √窗口天数。高 ≥ 2；中 ≥ 1 且 &lt; 2；低
                  &lt; 1。优先使用完整的 5
                  日窗口，否则使用首个完整窗口；缺少基准或波动率时标为不可评估。反应强度、涨跌方向和证据可信度是三个独立维度，不代表因果概率。
                </p>
              </details>
            </section>
            <EventsTable
              events={bundle.events.filter(
                (e) =>
                  e.symbols.includes(symbol) &&
                  (!rating ||
                    bundle.annotations.some(
                      (a) => a.symbol === symbol && a.event_id === e.id && a.rating === rating,
                    )),
              )}
              bundle={bundle}
              symbol={symbol}
              onSelect={onSelect}
            />
            <section className="insight-row">
              <div className="insight-icon">
                <FileText size={18} />
              </div>
              <div>
                <h3>可复核的研究摘录</h3>
                {bundle.claims
                  .filter((c) => c.id.includes(symbol))
                  .map((c) => (
                    <p key={c.id}>
                      {c.text}{' '}
                      <a
                        href={safeUrl(bundle.datasets[symbol].source_url)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        查看行情来源 ↗
                      </a>
                    </p>
                  ))}
                <small>数字来自已保存行情快照；事件相关性需结合原始证据判断。</small>
              </div>
            </section>
            <Disclosure bundle={bundle} />
          </>
        )}
        {tab === 'compare' && <CompareView bundle={bundle} onRevise={onRevise} />}
        {tab === 'data' && <DataView bundle={bundle} />}
        {tab === 'method' && <MethodView bundle={bundle} />}
        {tab === 'artifacts' && (
          <section className="surface prose">
            <h3>同一份研究，多种交付方式</h3>
            <p className="muted">
              所有文件使用该版本的研究数据、指标和引用。生成时间{' '}
              {bundle.created_at.slice(0, 16).replace('T', ' ')} UTC。
            </p>
            <div className="artifact-grid">
              {[
                ['html', '交互研究报告', '离线图表、事件与证据联动'],
                ['xlsx', '回测底稿', '原始数据、参数、公式与计算检查'],
                ['pptx', '决策框架', '可编辑的情景比较与决策结构'],
                ['docx', '策略报告', '方法、研究结论、来源与边界'],
              ]
                .filter(([format]) => bundle.spec.outputs.includes(format))
                .map(([format, title, description]) => (
                  <div className="artifact-item" key={format}>
                    <span className={`file-badge ${format}`}>{format.toUpperCase()}</span>
                    <h4>{title}</h4>
                    <p>{description}</p>
                    {artifactBase ? (
                      <a
                        className="button secondary"
                        href={`${artifactBase}/report.${format}`}
                        download
                      >
                        <Download size={14} /> 下载
                      </a>
                    ) : (
                      <span className="small muted">请使用同一交付包中的 report.{format}</span>
                    )}
                  </div>
                ))}
            </div>
            <p className="small muted">
              离线 HTML 不连接模型或数据服务。更新行情或继续研究需要运行应用。
            </p>
          </section>
        )}
      </div>
      <footer className="research-footer">
        <span>Evidence · 研究可追溯</span>
        <span>
          研究版本 {bundle.id} · 方法 {bundle.method_version ?? '未记录'}
        </span>
      </footer>
    </div>
  );
}
