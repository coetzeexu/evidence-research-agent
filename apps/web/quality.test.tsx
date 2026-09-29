import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { QualityPanel } from './QualityPanel';
import ResearchConversation from './ResearchConversation';
import { SensitivityPanel } from './SensitivityPanel';
import { candleOption } from '../../packages/charts/options.mjs';

it('displays incomplete named requirements without a success claim', () => {
  const bundle: any = {
    events: [],
    review: { passed: true },
    quality: {
      passed: false,
      changes: 2,
      associated_changes: 0,
      note: '关联不证明因果',
      requirements: [{ requirement: '模型首次发布', event_ids: [], status: 'missing' }],
      repair_actions: [],
      data_gaps: [],
      periods: [],
    },
  };
  const html = renderToStaticMarkup(<QualityPanel bundle={bundle} onSelect={() => {}} />);
  expect(html).toContain('研究仍有缺口');
  expect(html).toContain('尚未核实');
  expect(html).not.toContain('需求覆盖检查通过');
});

it('preserves delayed association hit targets and distinguishes them from event pins', () => {
  const bundle: any = {
    spec: { start: '2025-01-01', end: '2025-02-01' },
    datasets: {
      NVDA: {
        bars: [{ date: '2025-01-27', open: 100, close: 90, low: 80, high: 105, volume: 100 }],
      },
    },
    events: [{ id: 'e', title: '模型发布' }],
    annotations: [{ symbol: 'NVDA', event_id: 'e', date: '2025-01-20', price: 100, rating: '高' }],
    changes: [
      {
        symbol: 'NVDA',
        date: '2025-01-27',
        event_ids: ['e'],
        associations: [{ event_id: 'e', lag_bars: 4, reason: '候选关联' }],
      },
    ],
  };
  const marks: any = candleOption(bundle, 'NVDA').series.find(
    (s: any) => s.name === '异动候选关联',
  );
  expect(marks.data[0].value).toEqual(['2025-01-27', 90]);
  expect(marks.data[0].eventId).toBe('e');
  expect(marks.tooltip.formatter({ data: marks.data[0] })).toContain('不代表因果');
  expect(
    candleOption(bundle, 'NVDA', { rating: '低' }).series.find(
      (s: any) => s.name === '异动候选关联',
    )!.data,
  ).toHaveLength(0);
});

it('labels sensitivity snapshots and includes original configuration', () => {
  const bundle: any = {
    comparison: {
      sensitivity: {
        method: '下一开盘执行',
        caveat: '不是样本外检验',
        rows: [
          {
            dimension: 'baseline',
            label: '原始配置',
            start: '2023-01-01',
            end: '2024-01-01',
            cagr: 0.1,
            max_drawdown: -0.2,
            volatility: 0.3,
            total_cost: 50,
          },
        ],
      },
    },
  };
  const html = renderToStaticMarkup(<SensitivityPanel bundle={bundle} />);
  expect(html).toContain('原始配置');
  expect(html).toContain('不是样本外检验');
});

it('shows verified text and its partial status without links to unexported reports', () => {
  const bundle: any = {
    id: 'text-only',
    spec: { outputs: ['html', 'xlsx'] },
    datasets: {},
    sources: [],
    events: [],
    warnings: [],
    research: {
      status: 'partial',
      text: '已核验的有限结论。仍需核实事件公开日期。',
      questions: [],
    },
  };
  const noop = () => {};
  const html = renderToStaticMarkup(
    <ResearchConversation
      run={{ id: 'text-only', title: '研究', status: 'researched', mode: 'live', created_at: '' }}
      bundle={bundle}
      traces={[]}
      chat={[]}
      value=""
      onChange={noop}
      onSend={noop}
      busy={false}
      connection=""
      onReport={noop}
      onAction={noop}
      onClarify={noop}
    />,
  );
  expect(html).toContain('已核验的有限结论');
  expect(html).toContain('研究部分完成，含证据缺口');
  expect(html).not.toContain('/artifacts/report.');
  expect(html).not.toContain('研究报告已就绪');
});
