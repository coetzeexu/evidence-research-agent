// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { readFileSync } from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';
import { StandaloneReport } from './StandaloneReport';

vi.mock('./ChartLoader', () => ({
  Chart: ({ onEvent }: any) => <div data-testid="chart" onClick={() => onEvent?.('unused')} />,
}));
const snapshot = (name: string) =>
  JSON.parse(readFileSync(`${process.cwd()}/samples/${name}/bundle.json`, 'utf8'));
let root: ReturnType<typeof createRoot>;
let host: HTMLDivElement;
function mount(bundle: any) {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  act(() => root.render(<StandaloneReport bundle={bundle} />));
}
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
});

it('renders a continuous report with source links and no workspace or artifact tabs', () => {
  const bundle = snapshot('nvda');
  bundle.spec.assumptions.push('输出四种文件：html、xlsx、pptx、docx');
  mount(bundle);
  const text = host.textContent!;
  for (const label of ['研究摘要', '行情变化与事件时间线', '研究方法与限制', '数据底稿与来源索引'])
    expect(text).toContain(label);
  for (const label of [
    '研究范围与依据',
    '研究产物',
    '同一份研究，多种交付方式',
    'RESEARCH WORKSPACE',
    '请使用同一交付包',
  ])
    expect(text).not.toContain(label);
  expect(host.querySelector('.study-tabs')).toBeNull();
  expect(text).not.toContain('输出四种文件');
  expect(host.querySelector('a[href*="/artifacts/"]')).toBeNull();
  const contents = [...host.querySelectorAll('.report-contents a')];
  expect(contents.every((a) => host.querySelector(a.getAttribute('href')!))).toBe(true);
  expect(host.querySelectorAll('a[target="_blank"]').length).toBeGreaterThan(5);
});

it('filters events and opens evidence directly from the report timeline', () => {
  const bundle = snapshot('nvda');
  mount(bundle);
  const button = host.querySelector('.report-event-list button') as HTMLButtonElement;
  act(() => button.click());
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
  expect(host.querySelector('[role="dialog"] a[href^="https://"]')).not.toBeNull();
  act(() => (host.querySelector('[aria-label="关闭证据"]') as HTMLButtonElement).click());
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  const select = host.querySelectorAll('.report-controls select')[1] as HTMLSelectElement;
  act(() => {
    select.value = '高';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  const expected = bundle.events.filter(
    (e: any) =>
      e.symbols.includes('NVDA') &&
      bundle.annotations.some(
        (a: any) => a.symbol === 'NVDA' && a.event_id === e.id && a.rating === '高',
      ),
  ).length;
  expect(host.querySelectorAll('.report-event-list article')).toHaveLength(expected);
});

it('lists every marked move with an attribution state and links to its evidence', () => {
  const bundle = snapshot('nvda');
  const [linked, searched, blank] = bundle.changes.filter((c: any) => c.symbol === 'NVDA');
  linked.associations = [
    { event_id: bundle.events[0].id, lag_bars: 0, reason: 'r', source_ids: [] },
  ];
  linked.event_ids = [bundle.events[0].id];
  linked.attribution = { status: 'linked', queries: [], note: 'n' };
  searched.associations = [];
  searched.event_ids = [];
  searched.attribution = {
    status: 'investigated_unexplained',
    queries: ['NVDA q'],
    note: 'n',
    method: 'sweep',
    leads: [
      { title: 'Lead', url: 'https://example.com/lead' },
      { title: 'Bad', url: 'javascript:alert(1)' },
    ],
  };
  blank.associations = [];
  blank.event_ids = [];
  blank.attribution = { status: 'not_investigated', queries: [], note: 'n' };
  mount(bundle);
  const rows = host.querySelectorAll('.change-attribution tbody tr');
  expect(rows).toHaveLength(bundle.changes.filter((c: any) => c.symbol === 'NVDA').length);
  expect(host.querySelector('tr[data-status="investigated_unexplained"]')!.textContent).toContain(
    '已检索未发现',
  );
  const swept = host.querySelector('tr[data-status="investigated_unexplained"]')!;
  expect(swept.textContent).toContain('自动补查');
  expect(swept.textContent).toContain('未读取核验');
  const leads = [...swept.querySelectorAll('.attribution-leads a')] as HTMLAnchorElement[];
  expect(leads.map((a) => a.getAttribute('href'))).toEqual(['https://example.com/lead', null]);
  expect(host.querySelector('tr[data-status="not_investigated"]')!.textContent).toContain(
    '未专项检索',
  );
  const filter = [...host.querySelectorAll('.change-attribution-filter button')].find((b) =>
    b.textContent!.startsWith('已检索未发现'),
  ) as HTMLButtonElement;
  act(() => filter.click());
  expect(host.querySelectorAll('.change-attribution tbody tr')).toHaveLength(
    bundle.changes.filter(
      (c: any) => c.symbol === 'NVDA' && c.attribution?.status === 'investigated_unexplained',
    ).length,
  );
  act(() => (host.querySelector('.change-attribution-filter button') as HTMLButtonElement).click());
  act(() => (host.querySelector('.attribution-event') as HTMLButtonElement).click());
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
});

it('shows comparison chapters together without controls that pretend to rerun offline', () => {
  mount(snapshot('gold-bitcoin'));
  for (const label of ['组合执行与风险代价', '压力月份与抗跌表现', '通胀关联', '配置敏感性'])
    expect(host.textContent).toContain(label);
  expect(host.querySelector('input[type="number"]')).toBeNull();
  expect(host.textContent).not.toContain('重算此配置');
});
