// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from './App';
import type { Trace } from './types';

vi.mock('./ResearchView', () => ({
  ResearchView: ({ bundle }: { bundle: { id: string } }) => <div>研究视图 {bundle.id}</div>,
  EvidencePanel: () => null,
}));

class FakeEvents {
  static CLOSED = 2;
  static instances: FakeEvents[] = [];
  readyState = 1;
  onmessage?: (event: { data: string }) => void;
  onerror?: () => void;
  onopen?: () => void;
  listeners: Record<string, () => void> = {};
  constructor(public url: string) {
    FakeEvents.instances.push(this);
  }
  addEventListener(name: string, callback: () => void) {
    this.listeners[name] = callback;
  }
  emit(trace: Trace) {
    this.onmessage?.({ data: JSON.stringify(trace) });
  }
  close() {
    this.readyState = 2;
  }
}
let container: HTMLDivElement;
let root: Root;
const runs = ['first', 'second'].map((id) => ({
  id,
  title: `研究 ${id}`,
  status: 'complete',
  mode: 'live',
  created_at: '2026-09-28',
}));
const reply = (value: unknown) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
function button(label: string) {
  const result = [...container.querySelectorAll('button')].find((b) =>
    b.textContent?.includes(label),
  );
  if (!result) throw new Error(`Button absent: ${label}`);
  return result;
}
async function click(label: string) {
  await act(async () => {
    button(label).click();
  });
}
async function inputChat(value: string) {
  const element = container.querySelector('textarea')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(
      element,
      value,
    );
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
beforeEach(() => {
  FakeEvents.instances = [];
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('EventSource', FakeEvents);
  Element.prototype.scrollTo = vi.fn();
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.unstubAllGlobals();
});

it('keeps delayed answers in the originating research after the user switches studies', async () => {
  let finish!: (response: Response) => void;
  const delayed = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url === '/api/runs') return reply(runs);
      if (url === '/api/health') return reply({ model_configured: true, model: 'test' });
      const id = url.split('/')[3];
      if (url.endsWith('/chat')) return options?.method === 'POST' ? delayed : reply([]);
      if (url.endsWith('/bundle'))
        return reply({ id, sources: [], datasets: {}, events: [], spec: { outputs: ['html'] } });
      return reply(runs.find((r) => r.id === id));
    }),
  );
  await act(async () => {
    root.render(<App />);
  });
  await click('研究 first');
  await click('研究会话');
  await inputChat('解释最大回撤');
  await act(async () => {
    container.querySelector<HTMLButtonElement>('[aria-label="发送"]')!.click();
  });
  expect(container.textContent).toContain('解释最大回撤');
  await click('研究 second');
  await act(async () => {
    finish(reply({ answer: '只属于第一份研究的迟到回答' }));
  });
  expect(container.querySelector('.conversation-request')?.textContent).toContain('研究 second');
  expect(container.textContent).not.toContain('只属于第一份研究的迟到回答');
  expect(container.textContent).not.toContain('解释最大回撤');
});

function basicFetch(
  options: {
    post?: (body: Record<string, unknown>) => Promise<Response>;
    status?: () => string;
  } = {},
) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/health') return reply({ model_configured: true, model: 'test' });
    if (url === '/api/runs' && init?.method === 'POST')
      return options.post ? options.post(JSON.parse(String(init.body))) : reply({ id: 'created' });
    const created = {
      id: 'created',
      title: '新研究',
      prompt: '研究 Blackwell 的市场反应',
      status: options.status?.() || 'running',
      mode: 'live',
      created_at: '2026-09-28T10:00:00Z',
    };
    if (url === '/api/runs') return reply([...runs, created]);
    const id = url.split('/')[3];
    if (url.endsWith('/chat'))
      return init?.method === 'POST' ? reply({ answer: '基于证据的回答' }) : reply([]);
    if (url.endsWith('/bundle'))
      return reply({ id, sources: [], datasets: {}, events: [], spec: { outputs: ['html'] } });
    if (url.endsWith('/cancel') || url.endsWith('/retry')) return reply({ status: 'ok' });
    return reply(id === 'created' ? created : runs.find((r) => r.id === id));
  });
}
async function mount(fetcher = basicFetch()) {
  vi.stubGlobal('fetch', fetcher);
  await act(async () => {
    root.render(<App />);
  });
  return fetcher;
}
async function enter(extra: KeyboardEventInit = {}) {
  await act(async () => {
    container
      .querySelector('textarea')!
      .dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true, ...extra }),
      );
  });
}
const trace = (seq: number, kind: string, label: string, payload = {}): Trace => ({
  seq,
  kind,
  label,
  payload,
  at: '2026-09-28T10:00:10Z',
});

it('focuses a new question without adding a sidebar conversation before successful submission', async () => {
  const fetcher = await mount();
  await click('新建研究');
  const savedCount = container.querySelectorAll('.run-item').length;
  expect(container.querySelector('h1')?.textContent).toBe('今天，想研究什么？');
  expect(container.querySelector('.run-list')?.textContent).not.toContain('未命名');
  expect(document.activeElement).toBe(container.querySelector('textarea'));
  await inputChat('尚未发送的问题');
  await click('新建研究');
  expect(container.querySelector('textarea')?.value).toBe('尚未发送的问题');
  expect(container.querySelectorAll('.run-item')).toHaveLength(savedCount);
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
});

it('prefills a research idea without submitting and opens completed reports from the home library', async () => {
  const fetcher = await mount();
  await click('AI 事件与市场反应');
  expect(container.querySelector('textarea')?.value).toContain('NVDA 近五年');
  expect(document.activeElement).toBe(container.querySelector('textarea'));
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);

  await click('已完成的研究');
  const library = container.querySelector('[aria-label="研究起点"]')!;
  expect(library.textContent).toContain('研究 first');
  expect(library.textContent).not.toContain('新研究'); // The running study is not a completed report.
  const savedReport = [...library.querySelectorAll('button')].find((b) =>
    b.textContent?.includes('研究 second'),
  )!;
  await act(async () => savedReport.click());
  expect(container.querySelector('main')?.textContent).toContain('研究视图 second');
});

it('sends with Enter, but not Shift+Enter or an IME confirmation, and prevents duplicate submissions', async () => {
  let finish!: (r: Response) => void;
  const fetcher = await mount(
    basicFetch({
      post: () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    }),
  );
  await inputChat('研究 Blackwell 的市场反应');
  await enter({ shiftKey: true });
  await enter({ isComposing: true });
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
  await enter();
  await enter();
  const posts = fetcher.mock.calls.filter(([, options]) => options?.method === 'POST');
  expect(posts).toHaveLength(1);
  expect(JSON.parse(String(posts[0][1]?.body)).prompt).toBe('研究 Blackwell 的市场反应');
  expect(container.textContent).toContain('正在提交');
  await act(async () => {
    finish(reply({ id: 'created' }));
  });
  expect(container.querySelector('main')?.textContent).toContain('研究 Blackwell 的市场反应');
  expect(container.textContent).toContain('研究进行中');
});

it('retains the question and displays an actionable error when creation is rejected', async () => {
  await mount(
    basicFetch({
      post: async () =>
        new Response(JSON.stringify({ detail: '研究队列已满，请稍后再试' }), { status: 429 }),
    }),
  );
  await inputChat('不要丢失的研究问题');
  await click('开始研究');
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('研究队列已满');
  expect(container.querySelector('textarea')?.value).toBe('不要丢失的研究问题');
  expect(button('开始研究').disabled).toBe(false);
});

it('keeps the question and real pipeline history in the conversation after completion', async () => {
  let status = 'queued';
  await mount(basicFetch({ status: () => status }));
  await click('新研究');
  const events = FakeEvents.instances.at(-1)!;
  await act(async () => {
    events.onopen?.();
    events.emit(trace(1, 'step', '理解任务与解析资产', { phase: 'plan' }));
    events.emit(trace(2, 'step', '获取完整日线与宏观数据', { phase: 'collect' }));
    events.emit(trace(3, 'data', 'NVDA 行情已校验', { bars: 300 }));
    events.emit(trace(3, 'data', 'NVDA 行情已校验', { bars: 300 }));
    events.emit(
      trace(4, 'tool_failure', '原始来源读取失败', {
        url: 'https://example.org/source',
        error: 'HTTPError',
      }),
    );
  });
  expect(container.querySelector('main')?.textContent).toContain('研究 Blackwell 的市场反应');
  expect(container.textContent).toContain('300 根日线');
  expect(container.textContent).toContain('1 次来源读取失败');
  expect(container.textContent).toContain('4 条执行记录');
  await act(async () => {
    events.onerror?.();
  });
  expect(container.textContent).toContain('正在重连');
  await act(async () => {
    events.onopen?.();
  });
  expect(container.textContent).not.toContain('进度连接中断');
  status = 'complete';
  await act(async () => {
    events.emit(trace(5, 'complete', '研究产物已生成', { status: 'complete' }));
    events.emit(trace(6, 'model', '研究问答完成一次模型调用', { role: '研究问答' }));
    events.listeners.done();
  });
  expect(container.textContent).toContain('研究报告已就绪');
  expect(container.querySelector('main')?.textContent).toContain('研究 Blackwell 的市场反应');
  expect(container.querySelector('[aria-label="研究会话"]')).not.toBeNull();
  expect(
    container.querySelector('a[href="/api/runs/created/artifacts/report.html"]'),
  ).not.toBeNull();
  await click('获取完整日线与宏观数据');
  expect(container.textContent).toContain('NVDA 行情已校验');
  await inputChat('继续解释');
  await click('发送');
  expect(container.textContent).toContain('基于证据的回答');
  await click('查看研究报告');
  expect(container.textContent).toContain('研究视图 created');
  await click('研究会话');
  expect(container.textContent).toContain('基于证据的回答');
  expect(container.textContent).toContain('5 条执行记录');
});

it('does not navigate a user away from another study when a delayed creation completes', async () => {
  let finish!: (r: Response) => void;
  await mount(
    basicFetch({
      post: () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    }),
  );
  await inputChat('稍后创建');
  await click('开始研究');
  await click('研究 second');
  await act(async () => {
    finish(reply({ id: 'created' }));
  });
  expect(container.querySelector('.conversation-request')?.textContent).toContain('研究 second');
});

it('shows failed-stage recovery and subscribes again when retrying', async () => {
  let status = 'failed';
  const fetcher = await mount(basicFetch({ status: () => status }));
  await click('新研究');
  const previous = FakeEvents.instances.at(-1)!;
  await act(async () => {
    previous.emit(trace(1, 'step', '事件发现与原文核实', { phase: 'research' }));
  });
  expect(container.querySelector('.bui-thinking.failed')?.textContent).toContain('已中断');
  expect(container.querySelectorAll('.bui-thinking.complete')).toHaveLength(0);
  status = 'running';
  await click('从检查点继续');
  expect(fetcher.mock.calls.some(([url]) => url === '/api/runs/created/retry')).toBe(true);
  expect(previous.readyState).toBe(FakeEvents.CLOSED);
  expect(FakeEvents.instances.at(-1)).not.toBe(previous);
});

it('streams activity text and sources, folds completed steps and respects a manual collapse', async () => {
  await mount();
  await click('新研究');
  const events = FakeEvents.instances.at(-1)!;
  await act(async () => {
    events.emit(trace(1, 'step', '解析研究目标', { phase: 'plan' }));
    events.emit(trace(2, 'model_start', '主管处理', { call_id: 'model-1', role: '主管' }));
  });
  expect(container.textContent).toContain('主管正在处理');
  expect(container.querySelectorAll('.bui-thinking')).toHaveLength(1);
  expect(button('解析研究目标').getAttribute('aria-expanded')).toBe('true');
  await act(async () => {
    events.emit(trace(3, 'model', '主管完成', { call_id: 'model-1' }));
    events.emit(trace(4, 'step', '检索与阅读证据', { phase: 'research' }));
    events.emit(
      trace(5, 'model_start', '检索模型开始', { call_id: 'model-2', role: '研究子 Agent' }),
    );
    events.emit(
      trace(6, 'model_delta', '研究笔记', { call_id: 'model-2', text: '已经找到公开资料。' }),
    );
    events.emit(
      trace(7, 'source', '原始来源已读取', {
        source: {
          id: 'source-1',
          title: 'NVIDIA 官方原文',
          url: 'https://example.com/source',
          status: 'retrieved',
        },
      }),
    );
  });
  expect(button('解析研究目标').getAttribute('aria-expanded')).toBe('false');
  expect(container.textContent).toContain('已经找到公开资料。');
  expect(container.querySelector('.source-preview a')?.getAttribute('href')).toBe(
    'https://example.com/source',
  );
  await click('检索与阅读证据');
  await act(async () =>
    events.emit(
      trace(8, 'model_delta', '研究笔记', { call_id: 'model-2', text: '后续流式内容。' }),
    ),
  );
  expect(button('检索与阅读证据').getAttribute('aria-expanded')).toBe('false');
  expect(container.textContent).not.toContain('后续流式内容。');
  await click('检索与阅读证据');
  expect(container.textContent).toContain('已经找到公开资料。后续流式内容。');
});

it('follows the message end, pauses when reading above, and resumes on request', async () => {
  await mount();
  await click('新研究');
  const events = FakeEvents.instances.at(-1)!;
  const messages = container.querySelector('.conversation-messages')!;
  messages.getBoundingClientRect = () => ({ bottom: window.innerHeight }) as DOMRect;
  const bottom = container.querySelector('.conversation-thread')!.lastElementChild!;
  let bottomY = window.innerHeight;
  bottom.getBoundingClientRect = () => ({ bottom: bottomY }) as DOMRect;
  const scroll = vi.mocked(Element.prototype.scrollTo);
  await act(async () => messages.dispatchEvent(new Event('scroll')));
  scroll.mockClear();
  await act(async () => events.emit(trace(1, 'step', '检索证据', { phase: 'research' })));
  expect(scroll).toHaveBeenCalled();
  bottomY += 500;
  await act(async () => messages.dispatchEvent(new Event('scroll')));
  scroll.mockClear();
  await act(async () => events.emit(trace(2, 'model_start', '读取', { call_id: 'model-1' })));
  expect(scroll).not.toHaveBeenCalled();
  await click('回到最新进展');
  expect(scroll).toHaveBeenCalled();
});

it('folds an earlier failed attempt when a resumed step arrives', async () => {
  await mount();
  await click('新研究');
  const events = FakeEvents.instances.at(-1)!;
  await act(async () => {
    events.emit(trace(1, 'step', '首次检索', { phase: 'research' }));
    events.emit(trace(2, 'error', '首次请求中断'));
  });
  expect(button('首次检索').getAttribute('aria-expanded')).toBe('true');
  await act(async () => {
    events.emit(trace(3, 'step', '恢复检索', { phase: 'research' }));
  });
  expect(button('首次检索').getAttribute('aria-expanded')).toBe('false');
  expect(button('恢复检索').getAttribute('aria-expanded')).toBe('true');
  await click('首次检索');
  expect(button('首次检索').getAttribute('aria-expanded')).toBe('true');
});

it('renders chat deltas immediately and keeps a later streamed answer in its original conversation', async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const fallback = basicFetch();
  await mount(
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/chat') && init?.method === 'POST')
        return new Response(
          new ReadableStream<Uint8Array>({
            start(c) {
              controller = c;
            },
          }),
          { headers: { 'content-type': 'text/event-stream' } },
        );
      return fallback(url, init);
    }),
  );
  await click('研究 first');
  await click('研究会话');
  await inputChat('解释数据');
  await click('发送');
  const push = async (event: string, data: object) =>
    act(async () => {
      controller.enqueue(
        new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`),
      );
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  await push('delta', { text: '第一段实时内容' });
  expect(container.textContent).toContain('第一段实时内容');
  expect(container.querySelector('.streaming-cursor')).not.toBeNull();
  await push('delta', { text: '，第二段。' });
  expect(container.textContent).toContain('第一段实时内容，第二段。');
  await click('研究 second');
  await push('delta', { text: '仅第一份研究可见' });
  await push('done', { answer: '第一份研究的最终回答' });
  expect(container.querySelector('.conversation-request')?.textContent).toContain('研究 second');
  expect(container.textContent).not.toContain('第一份研究的最终回答');
});
