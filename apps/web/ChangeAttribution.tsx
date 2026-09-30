import { useState } from 'react';
import type { Bundle, ChangeAttributionStatus } from './types';
import { attributionLabel, changeAttribution, pct, safeUrl } from './types';
import './change-attribution.css';

const ORDER: ChangeAttributionStatus[] = ['linked', 'investigated_unexplained', 'not_investigated'];

/** Every marked move with its attribution state, so blanks are visibly searched or unsearched. */
export function ChangeAttributionTable({
  bundle,
  symbol,
  onSelect,
}: {
  bundle: Bundle;
  symbol: string;
  onSelect: (id: string) => void;
}) {
  const [status, setStatus] = useState<ChangeAttributionStatus | ''>('');
  const changes = bundle.changes.filter((c) => c.symbol === symbol);
  if (!changes.length) return null;
  const shown = changes.filter((c) => !status || changeAttribution(c).status === status);
  const titles = new Map(bundle.events.map((e) => [e.id, e.title]));
  return (
    <div className="change-attribution">
      <div className="change-attribution-heading">
        <h3>行情变化点与事件归因</h3>
        <div className="change-attribution-filter" role="group" aria-label="按归因状态筛选">
          {(['', ...ORDER] as const).map((key) => (
            <button key={key || 'all'} aria-pressed={status === key} onClick={() => setStatus(key)}>
              {key ? attributionLabel[key] : '全部'}
              <span>
                {key
                  ? changes.filter((c) => changeAttribution(c).status === key).length
                  : changes.length}
              </span>
            </button>
          ))}
        </div>
      </div>
      <div className="table-scroll">
        <table className="compact-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>变化</th>
              <th>幅度</th>
              <th>成交量 / 20 日中位</th>
              <th>归因状态</th>
              <th>候选事件或检索记录</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => {
              const attribution = changeAttribution(c);
              return (
                <tr key={c.id} data-status={attribution.status}>
                  <td>{c.date}</td>
                  <td>
                    {c.type}
                    {c.note && <small className="muted">{c.note}</small>}
                  </td>
                  <td>{pct(c.return)}</td>
                  <td>{c.volume_ratio == null ? '—' : `${c.volume_ratio.toFixed(1)}×`}</td>
                  <td>
                    <span
                      className={`attribution-tag ${attribution.status}`}
                      title={attribution.note}
                    >
                      {attributionLabel[attribution.status]}
                    </span>
                    {attribution.method === 'sweep' && (
                      <small className="attribution-method">自动补查</small>
                    )}
                  </td>
                  <td>
                    {(c.associations || []).map((link) => (
                      <button
                        className="attribution-event"
                        key={link.event_id}
                        onClick={() => onSelect(link.event_id)}
                        title={link.reason}
                      >
                        {titles.get(link.event_id) || link.event_id}
                        {link.lag_bars > 0 ? `（公开后第 ${link.lag_bars} 根日线）` : ''} ↗
                      </button>
                    ))}
                    {!c.associations?.length && (
                      <details>
                        <summary>{attribution.queries.length} 次窄窗检索</summary>
                        <small>{attribution.note}</small>
                        <ul>
                          {attribution.queries.map((q, i) => (
                            <li key={i}>{q}</li>
                          ))}
                        </ul>
                        {!!attribution.leads?.length && (
                          <>
                            <small>候选线索（未读取核验，不是证据）：</small>
                            <ul className="attribution-leads">
                              {attribution.leads.map((lead) => (
                                <li key={lead.url}>
                                  <a
                                    href={safeUrl(lead.url)}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    {lead.title}
                                  </a>
                                </li>
                              ))}
                            </ul>
                          </>
                        )}
                      </details>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="figure-note">
        变化点由确定性规则检出（日收益超过 1.6 倍历史波动，或 5
        日确认的局部低点回升）。“已关联”只表示来源支持的事件在变化前 0–5
        根日线内公开，不证明因果；“已检索未发现”保留为未解释变化，不用相近事件凑数；标“自动补查”的点由代码按窄窗检索一次，其候选线索未经读取核验。
      </p>
    </div>
  );
}
