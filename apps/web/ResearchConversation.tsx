import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, BookOpen, Check, Loader2, Square, X } from 'lucide-react';
import type { Bundle, ChatMessage, Run, Trace } from './types';
import PipelineProgress from './PipelineProgress';
import ChatComposer from './components/beautiful-ui/ChatComposer';
import { Button } from './components/beautiful-ui/Button';
import LoadingState from './components/beautiful-ui/LoadingState';
import StreamingText from './components/beautiful-ui/StreamingText';

export default function ResearchConversation({
  run,
  bundle,
  traces,
  chat,
  value,
  onChange,
  onSend,
  busy,
  compact = false,
  connection,
  onReport,
  onAction,
  onClarify,
  onClose,
}: {
  run: Run;
  bundle: Bundle | null;
  traces: Trace[];
  chat: ChatMessage[];
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
  compact?: boolean;
  connection: string;
  onReport: () => void;
  onAction: (action: 'cancel' | 'retry') => void;
  onClarify: () => void;
  onClose?: () => void;
}) {
  const bottom = useRef<HTMLDivElement>(null);
  const messages = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const [unseen, setUnseen] = useState(false);
  const running = ['queued', 'running'].includes(run.status);
  const sources = bundle
    ? [
        ...bundle.sources,
        ...Object.entries(bundle.datasets).map(([symbol, d]) => ({
          id: d.id,
          title: `${symbol} 行情快照`,
          url: d.source_url,
        })),
      ]
    : [];
  useEffect(() => {
    const target = messages.current;
    const onScroll = () => {
      if (!bottom.current) return;
      const viewportBottom = target?.getBoundingClientRect().bottom;
      if (viewportBottom == null) return;
      followLatest.current = bottom.current.getBoundingClientRect().bottom - viewportBottom < 100;
      if (followLatest.current) setUnseen(false);
    };
    target?.addEventListener('scroll', onScroll, { passive: true });
    return () => target?.removeEventListener('scroll', onScroll);
  }, []);
  function scrollToLatest() {
    const target = messages.current;
    if (target) target.scrollTo({ top: target.scrollHeight, behavior: 'auto' });
  }
  useEffect(() => {
    if (followLatest.current) scrollToLatest();
    else setUnseen(true);
  }, [traces.at(-1)?.seq, chat.at(-1)?.text, chat.length]);
  return (
    <section className={`research-conversation ${compact ? 'compact' : ''}`} aria-label="研究会话">
      {compact && (
        <header className="conversation-heading">
          <div>
            <span className="assistant-avatar">e</span>
            <strong>研究会话</strong>
          </div>
          {onClose && (
            <button className="icon-button" onClick={onClose} aria-label="关闭研究对话">
              <X size={15} />
            </button>
          )}
        </header>
      )}
      <div className="conversation-messages" ref={messages} tabIndex={0} aria-label="会话内容">
        <div className="conversation-thread">
          <article className="conversation-request">
            <small>{run.mode === 'sample' ? '研究任务' : '你'}</small>
            <p>{run.prompt || run.title}</p>
          </article>
          <article className="agent-response">
            <div className="agent-label">
              <span className="assistant-avatar">e</span>Evidence<span>研究助手</span>
            </div>
            <PipelineProgress
              run={run}
              traces={traces}
              compact={compact}
              connection={connection}
              sources={sources}
            />
            {bundle?.research?.text && (
              <div className="conversation-message assistant" aria-label="已核验研究正文">
                <StreamingText text={bundle.research.text} sources={sources} streaming={false} />
              </div>
            )}
            {bundle && (
              <div className="result-card">
                <div className="result-heading">
                  <Check size={16} />
                  <strong>
                    {bundle.research
                      ? bundle.research.status === 'complete'
                        ? '研究正文已核验'
                        : '已核验内容已就绪'
                      : run.status === 'partial'
                        ? '报告已生成 · 有待核实项'
                        : '研究报告已就绪'}
                  </strong>
                </div>
                <p>
                  {bundle.events.length} 个已核验事件 · {bundle.sources.length} 个来源
                </p>
                {bundle.research?.status === 'partial' && (
                  <div className="research-open-questions">
                    <strong>待核实事项</strong>
                    <ul>
                      {bundle.research.questions
                        .filter((q) => q.status !== 'answered')
                        .map((q) => (
                          <li key={q.id}>{q.question}</li>
                        ))}
                    </ul>
                    <p className="small muted">这些事项尚未形成结论，具体依据与边界见正文。</p>
                  </div>
                )}
                {!!bundle.warnings?.length && (
                  <details className="research-notes">
                    <summary>数据口径与研究说明</summary>
                    <ul>
                      {[...new Set(bundle.warnings)].map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  </details>
                )}
                <div className="result-actions">
                  {run.status !== 'researched' && (
                    <Button onClick={onReport}>
                      <BookOpen size={14} />
                      查看研究报告
                      <ArrowUpRight size={13} />
                    </Button>
                  )}
                  {run.status !== 'researched' &&
                    bundle.spec?.outputs.map((format) => (
                      <a
                        key={format}
                        href={`/api/runs/${bundle.id}/artifacts/report.${format}`}
                        download
                      >
                        {format.toUpperCase()} ↓
                      </a>
                    ))}
                </div>
              </div>
            )}
            {run.error && (
              <div className="error-box" role="status">
                {run.status === 'needs_input' ? (
                  run.error
                ) : (
                  <>
                    <p>本次执行未完成，已保存此前的研究记录。可以从检查点继续。</p>
                    <details>
                      <summary>查看错误详情</summary>
                      <p>{run.error}</p>
                    </details>
                  </>
                )}
              </div>
            )}
            {run.status === 'failed' && (
              <Button onClick={() => onAction('retry')} disabled={busy}>
                从检查点继续
              </Button>
            )}
          </article>
          {bundle &&
            chat.map((message, i) => (
              <article className={`conversation-message ${message.role}`} key={message.id || i}>
                <small>{message.role === 'user' ? '你' : 'Evidence'}</small>
                {message.role === 'user' ? (
                  <p>{message.text}</p>
                ) : (
                  <>
                    {!message.text && message.status === 'streaming' ? (
                      <LoadingState label="正在依据研究数据回答" />
                    ) : (
                      <StreamingText
                        text={message.text}
                        sources={sources}
                        streaming={message.status === 'streaming'}
                      />
                    )}
                    {message.status === 'interrupted' && (
                      <p className="answer-interrupted">回答中断，已保留收到的内容。</p>
                    )}
                  </>
                )}
              </article>
            ))}
          <div ref={bottom} />
        </div>
      </div>
      <div className="conversation-compose">
        {unseen && (
          <button
            className="follow-latest"
            onClick={() => {
              followLatest.current = true;
              setUnseen(false);
              scrollToLatest();
            }}
          >
            回到最新进展 ↓
          </button>
        )}
        {bundle ? (
          <>
            {!chat.length && (
              <div className="conversation-suggestions">
                {['这份研究有哪些局限？', '解释高反应事件的依据'].map((q) => (
                  <button key={q} onClick={() => onChange(q)}>
                    {q}
                    <ArrowUpRight size={12} />
                  </button>
                ))}
              </div>
            )}
            <ChatComposer
              value={value}
              onChange={onChange}
              onSend={() => {
                followLatest.current = true;
                setUnseen(false);
                onSend();
              }}
              label="发送"
              busy={busy}
              busyLabel="正在生成"
              placeholder="继续追问这份研究…"
            />
          </>
        ) : run.status === 'needs_input' ? (
          <ChatComposer
            value={value}
            onChange={onChange}
            onSend={onClarify}
            label="补充并继续"
            busy={busy}
            placeholder="补充资产或研究范围…"
          />
        ) : running ? (
          <div className="running-compose-note">
            <Loader2 size={14} className="spin" />
            <span>研究进行中</span>
            <Button onClick={() => onAction('cancel')} disabled={busy} variant="quiet">
              <Square size={12} />
              停止研究
            </Button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
