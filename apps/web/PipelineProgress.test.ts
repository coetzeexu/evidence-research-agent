import { expect, it } from 'vitest';
import { activityGroups, activityEntries, traceSources } from './activity';
import type { Trace } from './types';
const trace = (seq: number, kind: string, label: string, payload = {}): Trace => ({
  seq,
  kind,
  label,
  payload,
  at: '2026-09-28T10:00:00Z',
});
it('only displays steps that actually arrived, preserving repeated repair steps', () => {
  expect(activityGroups([], 'complete')).toEqual([]);
  const groups = activityGroups(
    ['plan', 'collect', 'research', 'review', 'research'].map((p, i) =>
      trace(i, 'step', p, { phase: p }),
    ),
    'running',
  );
  expect(groups.map((g) => g.title)).toEqual(['plan', 'collect', 'research', 'review', 'research']);
  expect(groups.map((g) => g.state)).toEqual([
    'complete',
    'complete',
    'complete',
    'complete',
    'running',
  ]);
  expect(new Set(groups.map((g) => g.id)).size).toBe(5);
});
it('does not turn a failed attempt into success when a new attempt is queued', () => {
  const records = [trace(1, 'step', '检索'), trace(2, 'error', '失败')];
  expect(activityGroups(records, 'queued')[0].state).toBe('failed');
  expect(activityGroups([trace(1, 'step', '计划')], 'needs_input')[0].state).toBe('paused');
});
it('reconstructs interleaved tool lifecycles and public text without duplicate replay chunks', () => {
  const records = [
    trace(1, 'step', '研究'),
    trace(2, 'model_start', '思考', { call_id: 'm' }),
    trace(3, 'model_delta', '文字', { call_id: 'm', text: '已经找到' }),
    trace(3, 'model_delta', '文字', { call_id: 'm', text: '已经找到' }),
    trace(4, 'model_delta', '文字', { call_id: 'm', text: '来源。' }),
    trace(5, 'model', '完成', { call_id: 'm' }),
    trace(6, 'tool_start', '读原文', { call_id: 'a', url: 'https://example.com/a' }),
    trace(7, 'tool_start', '检索', { call_id: 'b' }),
    trace(8, 'tool_end', '检索', { call_id: 'b' }),
    trace(9, 'tool_error', '读原文', { call_id: 'a' }),
  ];
  const entries = activityEntries(activityGroups(records, 'running')[0]);
  expect(entries[0]).toMatchObject({ text: '已经找到来源。', state: 'complete' });
  expect(entries[1]).toMatchObject({ tool: { status: 'failed' } });
  expect(entries[2]).toMatchObject({ tool: { status: 'complete' } });
});
it('freezes unfinished tools on cancellation and excludes later chat calls from research', () => {
  const groups = activityGroups(
    [
      trace(1, 'step', '检索'),
      trace(2, 'tool_start', '检索', { call_id: 't' }),
      trace(3, 'model_start', '追问', { role: '研究问答' }),
    ],
    'cancelled',
  );
  expect(groups[0].records).toHaveLength(2);
  expect(activityEntries(groups[0])[0]).toMatchObject({ tool: { status: 'interrupted' } });
});
it('upgrades discovered URLs to saved evidence without later search results downgrading them', () => {
  const candidate = {
    id: 'https://example.com',
    url: 'https://example.com',
    title: '线索',
    status: 'candidate',
  };
  const source = { ...candidate, id: 'source-1', title: '原始文档', status: 'retrieved' };
  expect(
    traceSources([
      trace(1, 'search_results', '检索', { sources: [candidate] }),
      trace(2, 'source', '读取', { source }),
      trace(3, 'search_results', '再次检索', { sources: [candidate] }),
    ]),
  ).toEqual([source]);
});
