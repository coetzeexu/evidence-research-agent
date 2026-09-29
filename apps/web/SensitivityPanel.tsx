import { useState } from 'react';
import type { Bundle } from './types';
import { pct } from './types';

export function SensitivityPanel({ bundle }: { bundle: Bundle }) {
  const [dimension, setDimension] = useState('all');
  const sensitivity = bundle.comparison.sensitivity;
  if (!sensitivity?.rows?.length) return null;
  const dimensions = [
    ['all', '全部'],
    ['weights', '权重'],
    ['cost', '成本'],
    ['frequency', '再平衡'],
    ['period', '历史区间'],
  ];
  return (
    <section className="surface">
      <div className="surface-title">
        <h3>配置敏感性</h3>
        <label>
          比较维度{' '}
          <select
            aria-label="敏感性比较维度"
            value={dimension}
            onChange={(e) => setDimension(e.target.value)}
          >
            {dimensions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted">{sensitivity.method}</p>
      <div className="table-scroll">
        <table className="compact-table">
          <thead>
            <tr>
              <th>情景</th>
              <th>区间</th>
              <th>年化收益</th>
              <th>最大回撤</th>
              <th>年化波动</th>
              <th>交易成本</th>
            </tr>
          </thead>
          <tbody>
            {sensitivity.rows
              .filter(
                (r: any) =>
                  dimension === 'all' || r.dimension === dimension || r.dimension === 'baseline',
              )
              .map((r: any) => (
                <tr key={`${r.dimension}-${r.label}`}>
                  <td>{r.label}</td>
                  <td>
                    {r.start} — {r.end}
                  </td>
                  <td>{pct(r.cagr)}</td>
                  <td>{pct(r.max_drawdown)}</td>
                  <td>{pct(r.volatility)}</td>
                  <td>${r.total_cost.toFixed(2)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <p className="small muted">{sensitivity.caveat}</p>
    </section>
  );
}
