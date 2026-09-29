// Adapted from Beautiful UI primitives/StreamingText.tsx (MIT).
// Retains streaming cursor, inline citation chips and expandable sources; SSE owns the text.
// No word timers, fixture text, fake counters or inactive action buttons.
import { useState } from 'react';
import { ChevronDown, Globe, ArrowUpRight } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { safeUrl, type StreamSource } from '../../types';

export default function StreamingText({
  text,
  sources = [],
  streaming = false,
  showAllSources = false,
}: {
  text: string;
  sources?: StreamSource[];
  streaming?: boolean;
  showAllSources?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const known = new Map(sources.filter((s) => safeUrl(s.url)).map((s) => [s.id, s]));
  const cited = new Set([...text.matchAll(/\[([^\]\n]+)\](?!\()/g)].map((match) => match[1]));
  const selected = [...known.values()].filter(
    (s) => showAllSources || cited.has(s.id) || text.includes(`](${s.url})`),
  );
  const linked = text.replace(/\[([^\]\n]+)\](?!\()/g, (original, id) => {
    const source = known.get(id);
    return source ? `[${id}](${source.url.replace(/\)/g, '%29')})` : original;
  });
  return (
    <div className={`bui-streaming ${streaming ? 'is-streaming' : ''}`}>
      {text && (
        <div className="streaming-prose">
          <ReactMarkdown
            components={{
              a: ({ href, children }) => {
                const source = selected.find((s) => s.url === href || s.id === String(children));
                return (
                  <a
                    href={href && safeUrl(href)}
                    target="_blank"
                    rel="noreferrer"
                    className={source ? 'inline-source' : undefined}
                    title={source?.title}
                  >
                    {source ? (
                      <>
                        <Globe size={11} />
                        {new URL(source.url).hostname.replace(/^www\./, '')}
                      </>
                    ) : (
                      children
                    )}
                  </a>
                );
              },
            }}
          >
            {linked}
          </ReactMarkdown>
        </div>
      )}
      {streaming && <span className="streaming-cursor" aria-label="正在接收内容" />}
      {!!selected.length && (
        <div className="streaming-sources">
          <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
            <span className="source-stack" aria-hidden="true">
              {selected.slice(0, 3).map((s) => (
                <i key={s.id}>
                  <Globe size={12} />
                </i>
              ))}
            </span>
            {selected.length} 个来源
            <ChevronDown size={12} className={expanded ? 'expanded' : ''} />
          </button>
          {expanded && (
            <div className="source-list">
              {selected.map((s) => (
                <a key={s.id} href={s.url} target="_blank" rel="noreferrer">
                  <Globe size={14} />
                  <span>
                    <strong>{s.title}</strong>
                    <small>
                      {new URL(s.url).hostname} ·{' '}
                      {s.status === 'candidate' ? '检索线索，待读取' : '已保存来源'}
                    </small>
                  </span>
                  <ArrowUpRight size={13} />
                </a>
              ))}
            </div>
          )}
          {!expanded && showAllSources && (
            <div className="source-preview">
              {selected.slice(0, 3).map((s) => (
                <a key={s.id} href={s.url} target="_blank" rel="noreferrer" title={s.title}>
                  <Globe size={11} />
                  <span>{s.title}</span>
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
