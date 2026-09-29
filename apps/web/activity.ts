import type { ActivityState } from './components/beautiful-ui/ThinkingState';
import type { StreamSource, Trace } from './types';
import type { ToolStep } from './components/beautiful-ui/ToolChips';

export type ActivityGroup = { id: string; title: string; records: Trace[]; state: ActivityState };
export function activityGroups(traces: Trace[], status: string): ActivityGroup[] {
  const groups: ActivityGroup[] = [];
  const seen = new Set<number>();
  for (const trace of [...traces].sort((a, b) => a.seq - b.seq)) {
    if (seen.has(trace.seq) || trace.kind === 'chat' || trace.payload.role === '研究问答') continue;
    seen.add(trace.seq);
    if (trace.kind === 'step' || !groups.length)
      groups.push({
        id: String(trace.seq),
        title: trace.kind === 'step' ? trace.label : '准备研究',
        records: [],
        state: 'complete',
      });
    groups.at(-1)!.records.push(trace);
  }
  for (const group of groups) {
    if (group.records.some((t) => t.kind === 'error')) group.state = 'failed';
  }
  const last = groups.at(-1);
  if (last && last.state !== 'failed')
    last.state =
      status === 'failed'
        ? 'failed'
        : ['needs_input', 'cancelled'].includes(status)
          ? 'paused'
          : ['running', 'queued'].includes(status)
            ? 'running'
            : 'complete';
  return groups;
}

export function traceSources(traces: Trace[]): StreamSource[] {
  const sources = new Map<string, StreamSource>();
  for (const t of traces) {
    const values = t.payload.source
      ? [t.payload.source]
      : Array.isArray(t.payload.sources)
        ? t.payload.sources
        : [];
    for (const item of values) {
      if (!item || typeof item !== 'object') continue;
      const s = item as StreamSource;
      if (typeof s.id !== 'string' || typeof s.url !== 'string' || typeof s.title !== 'string')
        continue;
      if (
        sources.get(s.url)?.status !== 'candidate' &&
        s.status === 'candidate' &&
        sources.has(s.url)
      )
        continue;
      sources.set(s.url, s);
    }
  }
  return [...sources.values()];
}

type ModelEntry = { kind: 'model'; id: string; text: string; label: string; state: ActivityState };
type ToolEntry = { kind: 'tool'; id: string; tool: ToolStep };
type NoteEntry = { kind: 'note'; id: string; text: string; warning: boolean };
type SourceEntry = { kind: 'sources'; id: string; text: string; sources: StreamSource[] };
export type ActivityEntry = ModelEntry | ToolEntry | NoteEntry | SourceEntry;

const detailFields: Record<string, string> = {
  query: '查询',
  url: '来源',
  provider: '检索服务',
  source_id: '来源 ID',
  error_type: '异常类型',
};
export function activityEntries(group: ActivityGroup): ActivityEntry[] {
  const entries: ActivityEntry[] = [];
  const models = new Map<string, ModelEntry>();
  const tools = new Map<string, ToolEntry>();
  const lifecycle = group.records.some((t) => t.kind === 'tool_start');
  for (const t of group.records) {
    const id = String(t.seq),
      callId = String(t.payload.call_id || id);
    if (['model_start', 'model_delta', 'model', 'model_error'].includes(t.kind)) {
      if (t.kind === 'model' && !t.payload.call_id) continue;
      let entry = models.get(callId);
      if (!entry) {
        entry = {
          kind: 'model',
          id: callId,
          text: '',
          label: `${t.payload.role || '研究助手'}正在处理`,
          state: 'running',
        };
        models.set(callId, entry);
        entries.push(entry);
      }
      if (t.kind === 'model_delta') entry.text += String(t.payload.text || '');
      if (t.kind === 'model') entry.state = 'complete';
      if (t.kind === 'model_error') entry.state = 'failed';
      continue;
    }
    if (['tool_start', 'tool_end', 'tool_error'].includes(t.kind)) {
      let entry = tools.get(callId);
      if (!entry) {
        entry = {
          kind: 'tool',
          id: callId,
          tool: {
            id: callId,
            label: t.label,
            chip: '',
            detail: [],
            kind: 'tool',
            time: t.at.slice(11, 19),
            status: 'running',
          },
        };
        tools.set(callId, entry);
        entries.push(entry);
      }
      entry.tool.detail.push(
        ...Object.entries(detailFields).flatMap(([key, label]) =>
          t.payload[key] == null ? [] : [`${label}：${t.payload[key]}`],
        ),
      );
      if (t.kind !== 'tool_start')
        entry.tool.status = t.kind === 'tool_error' ? 'failed' : 'complete';
      continue;
    }
    const sources = traceSources([t]);
    if (sources.length)
      entries.push({
        kind: 'sources',
        id,
        text: t.kind === 'data' ? `${t.label} · ${t.payload.bars} 根日线` : t.label,
        sources,
      });
    if (['tool', 'skill', 'tool_failure'].includes(t.kind)) {
      if (lifecycle) continue;
      entries.push({
        kind: 'tool',
        id,
        tool: {
          id,
          label: t.label,
          chip: String(t.payload.provider || ''),
          kind: t.kind,
          time: t.at.slice(11, 19),
          detail: Object.entries(detailFields).flatMap(([key, label]) =>
            t.payload[key] == null ? [] : [`${label}：${t.payload[key]}`],
          ),
          status: t.kind === 'tool_failure' ? 'failed' : 'recorded',
        },
      });
    } else if (!sources.length && !['step', 'complete'].includes(t.kind)) {
      let text = t.kind === 'error' ? '执行中断，已保留检查点。' : t.label;
      if (t.kind === 'plan')
        text += `：${((t.payload.symbols as string[]) || []).join('、')} · ${t.payload.start || ''} — ${t.payload.end || ''}`;
      if (t.kind === 'data') text += ` · ${t.payload.bars} 根日线`;
      if (Array.isArray(t.payload.assumptions) && t.payload.assumptions.length)
        text += `\n${t.payload.assumptions.join('\n')}`;
      entries.push({ kind: 'note', id, text, warning: ['error', 'warning'].includes(t.kind) });
    }
  }
  // A terminated phase must not keep a spinner alive after a disconnect/cancel/error.
  for (const entry of entries) {
    if (entry.kind === 'model' && entry.state === 'running' && group.state !== 'running')
      entry.state = group.state;
    if (entry.kind === 'tool' && entry.tool.status === 'running' && group.state !== 'running')
      entry.tool.status = 'interrupted';
  }
  return entries.filter((e) => e.kind !== 'model' || e.text || e.state !== 'complete');
}
