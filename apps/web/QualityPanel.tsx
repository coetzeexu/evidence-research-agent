import type { Bundle } from './types';

export function QualityPanel({
  bundle,
  onSelect,
}: {
  bundle: Bundle;
  onSelect: (id: string) => void;
}) {
  const q = bundle.quality;
  if (!q) return <p className="muted">历史快照尚未进行新版需求覆盖检查。</p>;
  const complete = q.passed && bundle.review.passed;
  return (
    <details className="surface quality-panel" open={!complete}>
      <summary>
        <strong>{complete ? '需求覆盖检查通过' : '执行已结束，研究仍有缺口'}</strong>
        <span className="muted">
          {' '}
          · {q.associated_changes} / {q.changes} 个变化有候选事件
        </span>
      </summary>
      <p className="small muted">{q.note}</p>
      {q.requirements.length > 0 && (
        <table className="compact-table">
          <caption>用户点名要求</caption>
          <thead>
            <tr>
              <th>要求</th>
              <th>证据事件</th>
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
