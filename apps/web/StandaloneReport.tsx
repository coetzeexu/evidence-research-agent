import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Chart } from './ChartLoader';
import { DataView, EvidencePanel } from './ResearchView';
import { SensitivityPanel } from './SensitivityPanel';
import { candleOption, comparisonOption, portfolioOption } from '../../packages/charts/options.mjs';
import type { Bundle } from './types';
import { linkCitations, pct, safeUrl } from './types';

function ReportSection({
  id,
  number,
  title,
  children,
}: {
  id: string;
  number: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="report-section" id={id}>
      <div className="report-section-heading">
        <span>{number}</span>
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function MarketChapter({ bundle, onSelect }: { bundle: Bundle; onSelect: (id: string) => void }) {
  const [symbol, setSymbol] = useState(bundle.spec.symbols[0]);
  const [rating, setRating] = useState('');
  const option = useMemo(() => candleOption(bundle, symbol, { rating }), [bundle, symbol, rating]);
  const events = bundle.events.filter(
    (e) =>
      e.symbols.includes(symbol) &&
      (!rating ||
        bundle.annotations.some(
          (a) => a.event_id === e.id && a.symbol === symbol && a.rating === rating,
        )),
  );
  const metrics = bundle.metrics.filter((m) => m.id === `performance-${symbol}`);
  return (
    <>
      <div className="report-controls">
        <label>
          标的{' '}
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {bundle.spec.symbols.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          事件反应{' '}
          <select value={rating} onChange={(e) => setRating(e.target.value)}>
            <option value="">全部</option>
            {['高', '中', '低', '不可评估'].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <a
          href={safeUrl(bundle.datasets[symbol].source_url)}
          target="_blank"
          rel="noopener noreferrer"
        >
          行情原始来源 ↗
        </a>
      </div>
      {metrics.map((m) => (
        <dl className="report-metrics" key={m.id}>
          {[
            ['累计收益', pct(m.total_return)],
            ['年化收益', pct(m.cagr)],
            ['年化波动', pct(m.volatility)],
            ['最大回撤', pct(m.max_drawdown)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ))}
      <Chart option={option} height={480} onEvent={onSelect} />
      <p className="figure-note">
        图 1 · 拆股调整 OHLC
        与成交量。滚轮或底部滑块缩放，点击标记查看原始证据。绿涨红跌；橙、蓝、灰标记分别表示高、中、低反应，菱形表示待解释变化。
      </p>
      <div className="report-event-list">
        {events.map((event) => {
          const annotation = bundle.annotations.find(
            (a) => a.symbol === symbol && a.event_id === event.id,
          );
          return (
            <article key={event.id}>
              <time>{event.date}</time>
              <div>
                <h3>
                  <button onClick={() => onSelect(event.id)}>{event.title} ↗</button>
                </h3>
                <p>{event.summary}</p>
                <small>
                  市场反应：{annotation?.rating ?? '不可评估'} · 证据可信度：
                  {{ high: '高', medium: '中', low: '低' }[event.confidence] ?? event.confidence}
                </small>
                <div className="report-source-links">
                  {event.source_ids.map((id) => {
                    const source = bundle.sources.find((s) => s.id === id);
                    return (
                      source && (
                        <a
                          key={id}
                          href={safeUrl(source.url)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {source.publisher || source.title} ↗
                        </a>
                      )
                    );
                  })}
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </>
  );
}

function ComparisonChapter({ bundle }: { bundle: Bundle }) {
  const [mode, setMode] = useState('normalized');
  const option = useMemo(() => comparisonOption(bundle, mode), [bundle, mode]);
  const portfolio = useMemo(() => portfolioOption(bundle), [bundle]);
  if (!bundle.comparison.anchors?.length)
    return <p>共同估值数据不足，暂不能形成同口径比较。详见数据与方法说明。</p>;
  return (
    <>
      <div className="report-controls">
        <label>
          观察指标{' '}
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="normalized">名义净值</option>
            <option value="real">实际购买力</option>
            <option value="drawdown">回撤</option>
          </select>
        </label>
        <span>共同月末估值 · 美元计价 · 初始指数 100</span>
      </div>
      <Chart option={option} height={360} />
      <p className="figure-note">
        图 2 · CPI 使用当前可得历史版本，购买力为事后回顾，不能当作当时的交易信号。
      </p>
      <h3>组合执行与风险代价</h3>
      <Chart option={portfolio} height={330} />
      <p className="figure-note">
        图 3 · 固定目标权重{' '}
        {bundle.spec.symbols.map((s, i) => `${s} ${pct(bundle.spec.weights[i])}`).join(' / ')}
        ；单边成本 {bundle.spec.cost_bps} bps；
        {bundle.spec.rebalance_months
          ? `每 ${bundle.spec.rebalance_months} 个月再平衡`
          : '买入持有'}
        。执行台账与月度近似分别展示。
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>资产</th>
              <th>累计收益</th>
              <th>年化波动</th>
              <th>最大回撤</th>
              <th>估值观测数</th>
            </tr>
          </thead>
          <tbody>
            {(bundle.comparison.asset_metrics || []).map((m: any) => (
              <tr key={m.symbol}>
                <th>{m.symbol}</th>
                <td>{pct(m.total_return)}</td>
                <td>{pct(m.volatility)}</td>
                <td>{pct(m.max_drawdown)}</td>
                <td>{m.observations}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>压力月份与抗跌表现</h3>
      <p className="figure-note">
        按基准最差月份事后选样；相对抗跌与正收益分别判断，不能推断所有危机均有效。
      </p>
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
                <td>{r.date}</td>
                <td>{pct(r.benchmark_return)}</td>
                {bundle.spec.symbols.map((s) => (
                  <td key={s}>{pct(r.returns[s])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>通胀关联</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>资产</th>
              <th>高通胀月均收益</th>
              <th>低通胀月均收益</th>
              <th>CPI 相关系数</th>
              <th>配对月份数</th>
            </tr>
          </thead>
          <tbody>
            {(bundle.comparison.inflation_summary || []).map((r: any) => (
              <tr key={r.symbol}>
                <th>{r.symbol}</th>
                <td>{pct(r.high_inflation_mean_return)}</td>
                <td>{pct(r.low_inflation_mean_return)}</td>
                <td>{r.inflation_correlation?.toFixed(3) ?? '—'}</td>
                <td>{r.high_inflation_n + r.low_inflation_n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <SensitivityPanel bundle={bundle} />
    </>
  );
}

export function StandaloneReport({ bundle }: { bundle: Bundle }) {
  const [eventId, setEventId] = useState<string | null>(null);
  const evidence = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!eventId) return;
    const previous = document.activeElement as HTMLElement | null;
    evidence.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return () => previous?.focus();
  }, [eventId]);
  const comparison = bundle.spec.symbols.length > 1;
  const hasText = !!bundle.research?.text;
  // Delivery choices belong to the application, not the report's methodology.
  const assumptions = bundle.spec.assumptions.filter(
    (item) =>
      !/(?:输出|导出|交付|生成|格式|文件).*(?:html|xlsx|pptx|docx|excel|ppt|word|报告|文件|产物)|(?:html|xlsx|pptx|docx|excel|ppt|word).*(?:输出|导出|交付|生成|格式|文件)/i.test(
        item,
      ),
  );
  return (
    <div className="standalone-report">
      <header className="report-masthead">
        <strong>EVIDENCE / RESEARCH</strong>
        <span>{bundle.created_at.slice(0, 10)}</span>
      </header>
      <main className="report-paper">
        <header className="report-cover">
          <p className="report-kicker">{comparison ? '资产比较研究' : '行情与事件研究'}</p>
          <h1>{bundle.spec.title}</h1>
          <p>
            {bundle.spec.start} — {bundle.spec.end} <span> / </span>{' '}
            {bundle.spec.symbols.join(' · ')} <span> / </span> 基准 {bundle.spec.benchmark}
          </p>
          <p className="report-status">
            {bundle.research?.status === 'complete'
              ? '研究快照'
              : bundle.research?.status === 'partial'
                ? '部分完成 · 尚有待核实事项'
                : bundle.research?.status === 'failed'
                  ? '研究核验未通过 · 仅供查看已保存的数据与缺口'
                  : '历史数据样例 · 研究正文未经本轮核验'}
          </p>
        </header>
        <nav className="report-contents" aria-label="报告目录">
          <a href="#findings">研究摘要</a>
          <a href="#market">行情与事件</a>
          {comparison && <a href="#comparison">资产比较</a>}
          <a href="#method">方法与限制</a>
          <a href="#sources">数据与来源</a>
        </nav>
        <ReportSection id="findings" number="01" title="研究摘要">
          {hasText ? (
            <div className="report-prose">
              <ReactMarkdown
                components={{
                  a: ({ href, children }) => (
                    <a href={href && safeUrl(href)} target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  ),
                }}
              >
                {linkCitations(bundle.research!.text, bundle)}
              </ReactMarkdown>
            </div>
          ) : (
            <>
              <p className="figure-note">
                以下为数据快照中的计算摘录，事件关联须结合原始来源复核。
              </p>
              {bundle.claims.map((claim) => {
                const ids = new Set([
                  ...claim.evidence_ids,
                  ...bundle.metrics
                    .filter((m) => claim.metric_ids.includes(m.id))
                    .flatMap((m) => m.dataset_ids || []),
                ]);
                const links = [
                  ...bundle.sources
                    .filter((s) => ids.has(s.id))
                    .map((s) => ({ id: s.id, url: s.url, title: s.title })),
                  ...Object.values(bundle.datasets)
                    .filter((d) => ids.has(d.id))
                    .map((d) => ({
                      id: d.id,
                      url: d.source_url,
                      title: d.instrument.symbol + ' 行情',
                    })),
                ];
                return (
                  <div key={claim.id}>
                    <p>{claim.text}</p>
                    <div className="report-source-links">
                      {links.map((s) => (
                        <a
                          key={s.id}
                          href={safeUrl(s.url)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {s.title} ↗
                        </a>
                      ))}
                    </div>
                  </div>
                );
              })}
            </>
          )}
        </ReportSection>
        <ReportSection id="market" number="02" title="行情变化与事件时间线">
          <MarketChapter bundle={bundle} onSelect={setEventId} />
        </ReportSection>
        {comparison && (
          <ReportSection id="comparison" number="03" title="避险、购买力与配置比较">
            <ComparisonChapter bundle={bundle} />
          </ReportSection>
        )}
        <ReportSection id="method" number={comparison ? '04' : '03'} title="研究方法与限制">
          <p>
            市场反应等级以相对基准收益的绝对值除以事前波动率与窗口长度平方根计算：高 ≥ 2，中 ≥ 1 且
            &lt; 2，低 &lt; 1。优先采用完整的 5
            日窗口，缺少基准或波动率时不评级。反应强度、涨跌方向与证据可信度分别表述，均不等于因果概率。
          </p>
          {comparison && (
            <p>
              比较采用共同月末估值，回测使用事前固定权重与下一可交易开盘执行。压力月份为事后选样；通胀相关性属于描述性统计，不能独自证明稳定抗通胀机制。
            </p>
          )}
          <ul>
            {[...assumptions, ...bundle.warnings].map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
          {bundle.disclosures.map((item) => (
            <div key={item.title}>
              <h3>{item.title}</h3>
              <p>
                {item.description} {item.reason} {item.limitations}{' '}
                <a href={safeUrl(item.url)} target="_blank" rel="noopener noreferrer">
                  产品原始资料 ↗
                </a>
              </p>
            </div>
          ))}
        </ReportSection>
        <ReportSection id="sources" number={comparison ? '05' : '04'} title="数据底稿与来源索引">
          <DataView bundle={bundle} />
        </ReportSection>
        <footer className="report-colophon">
          研究编号 {bundle.id} · 方法版本 {bundle.method_version ?? '未记录'}
          <br />
          本报告基于所列期间与来源快照；历史表现不保证未来结果。
        </footer>
      </main>
      {eventId && (
        <div className="report-evidence-overlay">
          <button
            className="report-evidence-backdrop"
            aria-label="关闭证据详情"
            onClick={() => setEventId(null)}
          />
          <aside
            ref={evidence}
            role="dialog"
            aria-modal="true"
            aria-label="事件证据详情"
            onKeyDown={(e) => {
              if (e.key === 'Escape') setEventId(null);
              if (e.key === 'Tab') {
                const nodes = evidence.current?.querySelectorAll<HTMLElement>(
                  'button, a[href], summary',
                );
                if (!nodes?.length) return;
                const first = nodes[0],
                  last = nodes[nodes.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last.focus();
                }
                if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first.focus();
                }
              }
            }}
          >
            <EvidencePanel
              bundle={bundle}
              eventId={eventId}
              sourceLabel="数据底稿与来源索引"
              onClose={() => setEventId(null)}
            />
          </aside>
        </div>
      )}
    </div>
  );
}
