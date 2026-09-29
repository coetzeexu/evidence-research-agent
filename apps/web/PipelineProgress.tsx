import { useEffect, useState } from 'react';
import { activityEntries, activityGroups, traceSources } from './activity';
import ToolChips from './components/beautiful-ui/ToolChips';
import ThinkingState from './components/beautiful-ui/ThinkingState';
import LoadingState from './components/beautiful-ui/LoadingState';
import StreamingText from './components/beautiful-ui/StreamingText';
import type { Run, StreamSource, Trace } from './types';

export default function PipelineProgress({
  run,
  traces,
  compact = false,
  connection,
  sources = [],
}: {
  run: Run;
  traces: Trace[];
  compact?: boolean;
  connection: string;
  sources?: StreamSource[];
}) {
  const running = ['queued', 'running'].includes(run.status);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  const groups = activityGroups(traces, run.status);
  const knownSources = [...sources, ...traceSources(traces)];
  const terminal = [...traces]
    .reverse()
    .find((t) => ['complete', 'error', 'cancelled'].includes(t.kind));
  const elapsed = Math.max(
    0,
    Math.round(
      ((running ? now : Date.parse(terminal?.at || run.updated_at || run.created_at)) -
        Date.parse(run.created_at)) /
        1000,
    ),
  );
  const duration = Number.isFinite(elapsed)
    ? elapsed < 60
      ? `${elapsed} 秒`
      : `${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒`
    : '';
  const tools = groups.reduce(
    (sum, g) =>
      sum +
      g.records.filter(
        (t) => t.kind === (g.records.some((r) => r.kind === 'tool_start') ? 'tool_start' : 'tool'),
      ).length,
    0,
  );
  return (
    <div
      className={`research-activity ${compact ? 'compact-activity' : ''}`}
      aria-label="研究执行过程"
    >
      {connection === 'reconnecting' && (
        <p role="status" className="connection-notice">
          进度连接中断，正在重连；后台任务继续运行。
        </p>
      )}
      {!groups.length &&
        (running || connection === 'connecting' ? (
          <LoadingState
            label={
              run.status === 'queued'
                ? '请求已保存，等待开始执行'
                : running
                  ? '正在连接研究过程'
                  : '正在读取研究记录'
            }
            elapsed={duration}
          />
        ) : (
          <p className="muted">这份研究未附带逐步执行记录，可直接查看已保存的报告与来源。</p>
        ))}
      {groups.map((group) => {
        const entries = activityEntries(group);
        const sourceCount = traceSources(group.records).length;
        return (
          <ThinkingState
            key={group.id}
            title={group.title}
            state={group.state}
            autoExpand={group.id === groups.at(-1)?.id && group.state !== 'complete'}
            meta={`${sourceCount ? `${sourceCount} 个来源 · ` : ''}${{ running: '进行中', complete: '完成', failed: '已中断', paused: '已暂停' }[group.state]}`}
          >
            {entries.map((entry) =>
              entry.kind === 'model' ? (
                <div key={entry.id} className="activity-model">
                  {entry.text ? (
                    <>
                      <small>
                        研究笔记 ·{' '}
                        {entry.state === 'running'
                          ? '正在生成'
                          : entry.state === 'complete'
                            ? '本步记录'
                            : '生成中断'}
                        ，结论以核验报告为准
                      </small>
                      <StreamingText
                        text={entry.text}
                        sources={knownSources}
                        streaming={entry.state === 'running'}
                      />
                    </>
                  ) : entry.state === 'running' ? (
                    <LoadingState label={entry.label} />
                  ) : (
                    <p className="activity-note">本次调用中断，已保留记录。</p>
                  )}
                </div>
              ) : entry.kind === 'tool' ? (
                <ToolChips key={entry.id} steps={[entry.tool]} />
              ) : entry.kind === 'sources' ? (
                <StreamingText
                  key={entry.id}
                  text={entry.text}
                  sources={entry.sources}
                  showAllSources
                />
              ) : (
                <p key={entry.id} className={`activity-note ${entry.warning ? 'warning' : ''}`}>
                  {entry.text}
                </p>
              ),
            )}
            {group.state === 'running' &&
              !entries.some(
                (e) =>
                  (e.kind === 'model' && e.state === 'running') ||
                  (e.kind === 'tool' && e.tool.status === 'running'),
              ) && <LoadingState label={group.title} />}
          </ThinkingState>
        );
      })}
      {!!groups.length && (
        <div className="pipeline-meta">
          <span>
            {tools} 次工具调用 · {traces.length} 条执行记录
          </span>
          <span>
            {running ? '已运行' : '历时'} {duration}
          </span>
        </div>
      )}
    </div>
  );
}
