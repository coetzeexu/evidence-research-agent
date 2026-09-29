import { describe, expect, it } from 'vitest';
import { pct, safeUrl } from './types';
import { candleOption, comparisonOption } from '../../packages/charts/options.mjs';

describe('research presentation contracts', () => {
  it('missing data stays missing', () => {
    expect(pct(null)).toBe('—');
    expect(pct(Number.NaN)).toBe('—');
    expect(pct(-0.123)).toBe('-12.3%');
  });
  it('rejects executable source URLs', () => {
    expect(safeUrl('javascript:alert(1)')).toBeUndefined();
    expect(safeUrl('data:text/html,x')).toBeUndefined();
  });
  it('keeps event IDs through chart hit testing and filters ratings', () => {
    const bundle = {
      spec: { start: '2024-01-01', end: '2024-12-31' },
      datasets: {
        NVDA: {
          bars: [{ date: '2024-03-18', open: 90, close: 91, low: 88, high: 94, volume: 100 }],
        },
      },
      events: [{ id: 'e', title: '发布' }],
      annotations: [
        {
          symbol: 'NVDA',
          date: '2024-03-18',
          price: 91,
          event_id: 'e',
          rating: '高',
          direction: '上涨',
        },
      ],
      changes: [],
    };
    const option = candleOption(bundle, 'NVDA', { rating: '高' });
    expect(option.series[0].data[0]).toEqual([90, 91, 88, 94]);
    expect(option.series[2].data[0].eventId).toBe('e');
    expect(candleOption(bundle, 'NVDA', { rating: '低' }).series[2].data).toHaveLength(0);
  });
  it('does not connect missing CPI observations', () => {
    const option = comparisonOption(
      { comparison: { series: [{ symbol: 'GLD', dates: ['a', 'b'], real: [100, null] }] } },
      'real',
    );
    expect(option.series[0].connectNulls).toBe(false);
  });
});

it('encodes reaction strength independently of price direction and keeps unavailable distinct', () => {
  const annotations = ['高', '中', '低', '不可评估'].flatMap((rating, index) =>
    ['上涨', '下跌'].map((direction, side) => ({
      symbol: 'NVDA',
      date: '2024-03-18',
      price: 91,
      event_id: `${index}-${side}`,
      rating,
      direction,
      confidence: 'medium',
      direction_window_days: 5,
      windows: [{ days: 5, complete: true, relative_return: direction === '上涨' ? 0.02 : -0.02 }],
    })),
  );
  const bundle = {
    spec: { start: '2024-01-01', end: '2024-12-31' },
    datasets: {
      NVDA: { bars: [{ date: '2024-03-18', open: 90, close: 91, low: 88, high: 94, volume: 100 }] },
    },
    events: [],
    annotations,
    changes: [],
  };
  const option = candleOption(bundle, 'NVDA');
  const marks = option.series[2].data as any[];
  for (let i = 0; i < marks.length; i += 2)
    expect(marks[i].itemStyle.color).toBe(marks[i + 1].itemStyle.color);
  expect(new Set(marks.map((m) => m.itemStyle.color)).size).toBe(4);
  expect(marks.filter((_, i) => i % 2 === 0).map((m) => m.label.formatter)).toEqual([
    '高',
    '中',
    '低',
    '?',
  ]);
  expect(marks[0].symbolSize).toBeGreaterThan(marks[2].symbolSize);
  expect(marks[2].symbolSize).toBeGreaterThan(marks[4].symbolSize);
  expect(new Set(marks.map((m) => m.symbolOffset[0])).size).toBe(8);
  const tooltip = (option.series[2].tooltip as any).formatter({ data: marks[1] });
  expect(tooltip).toContain('市场反应：高');
  expect(tooltip).toContain('下跌（5 根日线）');
  expect(tooltip).toContain('-2.00%');
  expect(tooltip).toContain('关联可信度：中');
  expect(candleOption(bundle, 'NVDA', { rating: '不可评估' }).series[2].data).toHaveLength(2);
});
