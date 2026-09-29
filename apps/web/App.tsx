import { useEffect, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowUpRight,
  BookOpen,
  ChevronRight,
  CircleHelp,
  MessageSquare,
  Plus,
  Search,
  X,
} from 'lucide-react';
import { EvidencePanel, ResearchView } from './ResearchView';
import ResearchConversation from './ResearchConversation';
import ChatComposer from './components/beautiful-ui/ChatComposer';
import { Button } from './components/beautiful-ui/Button';
import ResearchHelp from './ResearchHelp';
import type { Bundle, ChatMessage, Run, Spec, Trace } from './types';
import { readChatStream } from './chat-stream';

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    `/api${path}`,
    body
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      : undefined,
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请检查参数');
  return data;
}
const statusText: Record<string, string> = {
  queued: '等待执行',
  running: '研究中',
  complete: '已完成',
  partial: '已生成 · 有待核实项',
  failed: '执行失败',
  cancelled: '已取消',
  needs_input: '待补充',
  researched: '正文就绪',
};
const examples = [
  {
    icon: 'NVDA',
    category: '事件研究',
    theme: 'market',
    title: 'AI 事件与市场反应',
    description: '英伟达五年行情 · 关键事件 · 证据链',
    prompt:
      '回顾英伟达 NVDA 近五年行情，梳理 ChatGPT、Blackwell B100、DeepSeek 等 AI 大事件，标注行情变化、市场反应强度与证据可信度，生成交互报告。',
  },
  {
    icon: 'GLD / BTC',
    category: '资产比较',
    theme: 'allocation',
    title: '黄金 × 比特币',
    description: '避险与购买力 · 压力情景 · 配置回测',
    prompt:
      '比较黄金 GLD 与比特币 BTC-USD 近五年的避险与抗通胀表现，以 SPY 为压力基准，等权配置、月度再平衡、交易成本 10 bps，生成 HTML、Excel、PPT、Word。',
  },
];

export default function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Run | null>(null);
  const [view, setView] = useState<'conversation' | 'report'>('conversation');
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [eventId, setEventId] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const chatRequests = useRef(new Set<string>());
  const [chatInput, setChatInput] = useState('');
  const [filter, setFilter] = useState('');
  const [homeTab, setHomeTab] = useState<'ideas' | 'samples'>('ideas');
  const [streamVersion, setStreamVersion] = useState(0);
  const [connection, setConnection] = useState('connecting');
  const selectionVersion = useRef(0);
  const creating = useRef(false);
  const draftInput = useRef<HTMLTextAreaElement>(null);
  const run = detail?.id === selected ? detail : runs.find((r) => r.id === selected);
  const visibleBundle = bundle?.id === selected ? bundle : null;
  const reportVisible = view === 'report' && !!visibleBundle;

  async function refresh() {
    const list = await api<Run[]>('/runs');
    setRuns(list);
    return list;
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!selected) draftInput.current?.focus();
  }, [selected]);
  useEffect(() => {
    const version = ++selectionVersion.current;
    setBundle(null);
    setDetail(null);
    setEventId(null);
    setTraces([]);
    setChat([]);
    setChatInput('');
    setBusy(false);
    setError('');
    setConnection('connecting');
    if (!selected) return;
    let disposed = false;
    async function load() {
      const d = await api<Run>(`/runs/${selected}`);
      if (disposed) return;
      setDetail(d);
      setRuns((previous) => previous.map((item) => (item.id === d.id ? d : item)));
      if (['complete', 'partial', 'researched'].includes(d.status)) {
        const b = await api<Bundle>(`/runs/${selected}/bundle`);
        if (!disposed) setBundle(b);
      }
      const messages = await api<typeof chat>(`/runs/${selected}/chat`);
      if (!disposed && !chatRequests.current.has(selected!)) setChat(messages);
    }
    load().catch((e) => !disposed && setError(e.message));
    const events = new EventSource(`/api/runs/${selected}/events`);
    events.onopen = () => {
      if (!disposed) setConnection('connected');
    };
    events.onmessage = (event) => {
      if (disposed) return;
      try {
        const t = JSON.parse(event.data) as Trace;
        if (t.kind === 'step') {
          setDetail((previous) =>
            previous?.id === selected && previous.status === 'queued'
              ? { ...previous, status: 'running' }
              : previous,
          );
          setRuns((previous) =>
            previous.map((item) =>
              item.id === selected && item.status === 'queued'
                ? { ...item, status: 'running' }
                : item,
            ),
          );
        }
        if (t.kind !== 'chat' && t.payload.role !== '研究问答')
          setTraces((previous) =>
            previous.some((p) => p.seq === t.seq)
              ? previous
              : [...previous, t].sort((a, b) => a.seq - b.seq),
          );
      } catch {
        setError('一条进度记录读取失败，后续记录仍会继续更新。');
      }
    };
    events.addEventListener('done', () => {
      events.close();
      if (disposed) return;
      setConnection('done');
      load().catch((e) => !disposed && setError(e.message));
      refresh().catch((e) => !disposed && setError(e.message));
    });
    events.onerror = () => {
      if (!disposed) setConnection('reconnecting');
    };
    return () => {
      disposed = true;
      events.close();
      if (selectionVersion.current === version) selectionVersion.current++;
    };
  }, [selected, streamVersion]);

  function newResearch() {
    setSelected(null);
    setView('conversation');
    setError('');
    draftInput.current?.focus();
  }
  function selectRun(item: Run, target: 'conversation' | 'report' = 'conversation') {
    setSelected(item.id);
    setView(
      ['queued', 'running', 'needs_input', 'failed', 'cancelled'].includes(item.status)
        ? 'conversation'
        : target,
    );
    setChatOpen(false);
  }
  async function create(prompt: string, spec?: Spec, parent?: string) {
    if (!prompt.trim() || creating.current) return;
    creating.current = true;
    const version = selectionVersion.current;
    setBusy(true);
    setError('');
    try {
      const result = await api<{ id: string }>('/runs', {
        prompt,
        spec,
        parent_id: parent,
      });
      const pending: Run = {
        id: result.id,
        title: prompt.slice(0, 80),
        prompt,
        spec,
        status: 'queued',
        mode: 'live',
        created_at: new Date().toISOString(),
        parent_id: parent,
      };
      setRuns((previous) => [pending, ...previous]);
      if (selectionVersion.current === version) {
        setSelected(result.id);
        setView('conversation');
        setInput('');
        setChatOpen(false);
      }
      refresh().catch(() => {
        /* The saved run is already visible; its detail request remains authoritative. */
      });
    } catch (e) {
      if (selectionVersion.current === version) setError((e as Error).message);
    } finally {
      creating.current = false;
      if (selectionVersion.current === version) setBusy(false);
    }
  }
  async function sendChat() {
    const value = chatInput.trim();
    if (!value || !selected || busy || chatRequests.current.has(selected)) return;
    const version = selectionVersion.current;
    const origin = selected;
    const replyId = crypto.randomUUID();
    chatRequests.current.add(origin);
    setChatInput('');
    setBusy(true);
    setError('');
    setChat((c) => [
      ...c,
      { role: 'user', text: value },
      { role: 'assistant', text: '', id: replyId, status: 'streaming' },
    ]);
    try {
      const response = await fetch(`/api/runs/${origin}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: value, selected_id: eventId, stream: true }),
      });
      const answer = await readChatStream(response, (text) => {
        if (selectionVersion.current === version)
          setChat((c) => c.map((m) => (m.id === replyId ? { ...m, text: m.text + text } : m)));
      });
      if (selectionVersion.current === version)
        setChat((c) =>
          c.map((m) => (m.id === replyId ? { ...m, text: answer, status: 'complete' } : m)),
        );
    } catch (e) {
      if (selectionVersion.current === version) {
        setError((e as Error).message);
        setChatInput(value);
        setChat((c) => c.map((m) => (m.id === replyId ? { ...m, status: 'interrupted' } : m)));
      }
    } finally {
      chatRequests.current.delete(origin);
      if (selectionVersion.current === version) setBusy(false);
    }
  }
  async function runAction(action: 'cancel' | 'retry') {
    if (!selected || busy) return;
    const version = selectionVersion.current;
    setBusy(true);
    setError('');
    try {
      await api(`/runs/${selected}/${action}`, {});
      const list = await refresh();
      if (selectionVersion.current === version) {
        setDetail((previous) =>
          previous ? { ...previous, ...list.find((r) => r.id === selected) } : previous,
        );
        if (action === 'retry') setStreamVersion((v) => v + 1);
      }
    } catch (e) {
      if (selectionVersion.current === version) setError((e as Error).message);
    } finally {
      if (selectionVersion.current === version) setBusy(false);
    }
  }
  function downloads() {
    setView('report');
    // The report mounts after the tab switch; use an explicit requested tab prop.
    setReportTab({ tab: 'artifacts' });
  }
  const [reportTab, setReportTab] = useState<{ tab: string } | undefined>();
  const conversation = (compact = false) =>
    run && (
      <ResearchConversation
        key={`${run.id}-${compact}`}
        run={run}
        bundle={visibleBundle}
        traces={traces}
        chat={chat}
        value={chatInput}
        onChange={setChatInput}
        onSend={sendChat}
        busy={busy}
        compact={compact}
        connection={connection}
        onReport={() => {
          setView('report');
          setReportTab({ tab: 'market' });
        }}
        onAction={runAction}
        onClarify={() => create(chatInput, undefined, selected!)}
        onClose={compact ? () => setChatOpen(false) : undefined}
      />
    );

  return (
    <div className={`app-shell ${!selected ? 'home-active' : ''}`}>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setSelected(null);
          }}
        >
          <span className="brand-mark">e</span>
          <span>
            Evidence<small>RESEARCH WORKSPACE</small>
          </span>
        </a>
        <button
          className="new-study"
          onClick={newResearch}
          aria-current={!selected ? 'page' : undefined}
        >
          <Plus size={16} />
          新建研究
        </button>
        <label className="sidebar-search">
          <Search size={14} />
          <input
            aria-label="搜索研究"
            placeholder="搜索研究"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </label>
        <div className="sidebar-label">
          研究会话<span>{runs.length}</span>
        </div>
        <div className="run-list">
          {runs
            .filter((r) => r.title.toLowerCase().includes(filter.toLowerCase()))
            .map((r) => (
              <button
                className={`run-item ${selected === r.id ? 'active' : ''}`}
                key={r.id}
                onClick={() => selectRun(r)}
              >
                <BookOpen size={15} />
                <div>
                  <strong>{r.title}</strong>
                  <small>
                    <i
                      className={`status-dot ${r.status === 'complete' ? 'done' : r.status === 'failed' ? 'warning' : ''}`}
                    />
                    {r.mode === 'sample' ? '研究快照' : statusText[r.status]} ·{' '}
                    {r.created_at.slice(5, 10)}
                  </small>
                </div>
              </button>
            ))}
          {!runs.length && <p className="sidebar-empty">发送第一个问题后，会话会保存在这里。</p>}
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <nav className="breadcrumb" aria-label="面包屑">
            <button onClick={() => setSelected(null)}>研究空间</button>
            <ChevronRight size={12} />
            <strong title={run?.title}>{selected ? run?.title || '研究会话' : '首页'}</strong>
          </nav>
          <div className="actions">
            <button className="mobile-new icon-button" onClick={newResearch} aria-label="新建研究">
              <Plus size={17} />
            </button>
            {selected && (
              <div className="workspace-tabs" aria-label="会话与报告">
                <button aria-pressed={!reportVisible} onClick={() => setView('conversation')}>
                  <MessageSquare size={13} />
                  研究会话
                </button>
                <button
                  aria-pressed={reportVisible}
                  disabled={!visibleBundle}
                  onClick={() => {
                    setView('report');
                    setReportTab(undefined);
                  }}
                >
                  <BookOpen size={13} />
                  研究报告
                </button>
              </div>
            )}
            {visibleBundle && (
              <>
                <Button onClick={downloads}>
                  <ArrowDownToLine size={14} />
                  导出
                </Button>
                {reportVisible && (
                  <button
                    className={`icon-button ${chatOpen ? 'selected' : ''}`}
                    onClick={() => {
                      setEventId(null);
                      setChatOpen(!chatOpen);
                    }}
                    aria-label="切换研究对话"
                  >
                    <MessageSquare size={17} />
                  </button>
                )}
              </>
            )}
            {!selected && <ResearchHelp />}
          </div>
        </header>
        {error && (
          <div className="error-banner" role="alert">
            <CircleHelp size={16} />
            <span>{error}</span>
            <button className="icon-button" onClick={() => setError('')} aria-label="关闭错误提示">
              <X size={14} />
            </button>
          </div>
        )}
        <div className="workspace-content">
          {!selected ? (
            <div className="home-scroll" tabIndex={0} aria-label="首页内容区域">
              <main className="home">
                <h1>今天，想研究什么？</h1>
                <p className="home-description">从一个问题出发，连接行情、事件与原始证据。</p>
                <div className="home-composer">
                  <ChatComposer
                    inputRef={draftInput}
                    value={input}
                    onChange={setInput}
                    onSend={() => create(input)}
                    label="开始研究"
                    busy={busy}
                    placeholder="输入资产、时间范围和你想研究的问题…"
                  />
                </div>
                <section className="home-library" aria-label="研究起点">
                  <div className="home-section-title">
                    <div className="home-categories" aria-label="首页内容">
                      <button
                        aria-pressed={homeTab === 'ideas'}
                        onClick={() => setHomeTab('ideas')}
                      >
                        研究灵感
                      </button>
                      <button
                        aria-pressed={homeTab === 'samples'}
                        onClick={() => setHomeTab('samples')}
                      >
                        已完成的研究
                      </button>
                    </div>
                  </div>
                  {homeTab === 'ideas' ? (
                    <div className="example-grid">
                      {examples.map((e) => (
                        <button
                          className="example-card"
                          key={e.title}
                          onClick={() => {
                            setInput(e.prompt);
                            draftInput.current?.focus();
                          }}
                        >
                          <span className={`example-cover ${e.theme}`} aria-hidden="true">
                            <span className="example-category">{e.category}</span>
                            <span className="example-symbol">{e.icon}</span>
                            <ArrowUpRight size={20} />
                          </span>
                          <span className="example-copy">
                            <strong>{e.title}</strong>
                            <span>{e.description}</span>
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="home-recent">
                      {runs
                        .filter((r) => ['complete', 'partial', 'researched'].includes(r.status))
                        .map((r) => (
                          <button key={r.id} onClick={() => selectRun(r, 'report')}>
                            <span className="recent-icon">
                              <BookOpen size={20} />
                            </span>
                            <span>
                              <strong>{r.title}</strong>
                              <small>
                                {r.mode === 'sample' ? '研究快照' : statusText[r.status]} ·{' '}
                                {r.created_at.slice(0, 10)}
                              </small>
                            </span>
                            <ArrowUpRight size={16} />
                          </button>
                        ))}
                      {!runs.some((r) =>
                        ['complete', 'partial', 'researched'].includes(r.status),
                      ) && (
                        <p className="home-library-empty">
                          完成第一份研究后，可以在这里回看报告和原始证据。
                        </p>
                      )}
                    </div>
                  )}
                </section>
              </main>
            </div>
          ) : reportVisible && visibleBundle ? (
            <div className={`workspace-layout ${chatOpen || eventId ? 'with-inspector' : ''}`}>
              <main className="workspace-main" tabIndex={0} aria-label="报告内容">
                <ResearchView
                  key={visibleBundle.id}
                  bundle={visibleBundle}
                  requestedTab={reportTab}
                  onSelect={(id) => {
                    setEventId(id);
                    setChatOpen(false);
                  }}
                  onRevise={(spec) => create('重算配置参数', spec, visibleBundle.id)}
                  artifactBase={`/api/runs/${visibleBundle.id}/artifacts`}
                />
              </main>
              {(eventId || chatOpen) && (
                <aside className="inspector">
                  {eventId ? (
                    <>
                      <EvidencePanel
                        bundle={visibleBundle}
                        eventId={eventId}
                        onClose={() => setEventId(null)}
                      />
                      <button
                        className="evidence-chat"
                        onClick={() => {
                          setChatInput(
                            `解释“${visibleBundle.events.find((e) => e.id === eventId)?.title}”的市场反应及不确定性。`,
                          );
                          setEventId(null);
                          setChatOpen(true);
                        }}
                      >
                        <MessageSquare size={14} />与 Agent 讨论研究
                      </button>
                    </>
                  ) : (
                    conversation(true)
                  )}
                </aside>
              )}
            </div>
          ) : (
            <main className="conversation-page">
              {run ? (
                conversation()
              ) : (
                <p className="muted" role="status">
                  正在读取会话…
                </p>
              )}
            </main>
          )}
        </div>
      </div>
    </div>
  );
}
