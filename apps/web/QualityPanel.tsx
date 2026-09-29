import type { Bundle } from './types';

export function QualityPanel({
  bundle,
  onSelect,
}: {
  bundle: Bundle;
  onSelect: (id: string) => void;
}) {
  const q = bundle.quality;
  if (!q) return <p className="muted">此历史快照未记录研究范围核对结果。</p>;
  const complete = bundle.research
    ? bundle.research.status === 'complete'
    : q.passed && bundle.review.passed;
  return (
    <details className="surface quality-panel" open={!complete}>
      <summary>
        <strong>研究范围与依据</strong>
        <span className="muted">{complete ? '已核对' : '有待核实事项'}</span>
      </summary>
      <p className="small muted">这里核对研究要求与资料覆盖，结论的依据和局限请见正文。</p>
      {q.changes > 0 && (
        <p className="small muted">
          {q.changes} 处主要行情波动中，{q.associated_changes}{' '}
          处找到了同期事件线索。时间接近不代表因果关系。
        </p>
      )}
      {q.requirements.length > 0 && (
        <table className="compact-table">
          <caption>要求核实的事件</caption>
          <thead>
            <tr>
              <th>要求</th>
              <th>已找到的依据</th>
            </tr>
          </thead>
          <tbody>
            {q.requirements.map((r) => (
              <tr key={r.requirement}>
                <td>{r.requirement}</td>
                <td>
                  {r.event_ids.length
                    ? r.event_ids.map((id) => (
                        <button className="text-button" key={id} onClick={() => onSelect(id)}>
                          {bundle.events.find((e) => e.id === id)?.title || id}
                        </button>
                      ))
                    : '尚未核实'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {q.repair_actions.length > 0 && (
        <ul>
          {q.repair_actions.map((a, i) => (
            <li key={`${a.kind}-${i}`}>
              {a.query}：{a.reason}
            </li>
          ))}
        </ul>
      )}
      {q.data_gaps.map((g) => (
        <p key={g}>{g}</p>
      ))}
      {q.periods.length > 0 && (
        <p className="small muted">
          时期覆盖：
          {q.periods
            .map(
              (p) =>
                `${p.start.slice(0, 4)} 年 ${p.event_ids.length} 个事件${!p.required ? '（边界片段）' : ''}`,
            )
            .join('；')}
        </p>
      )}
    </details>
  );
}
