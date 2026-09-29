// Adapted from Beautiful UI's ToolChips.tsx (MIT); see LICENSE and README.md.
// Only the expandable tool rows are retained. No staged demos or file-diff fixtures.
import { useEffect, useRef, useState } from 'react';
import {
  ChevronRight,
  FileSearch,
  AlertTriangle,
  Search,
  Database,
  Check,
  Loader2,
} from 'lucide-react';

export type ToolStep = {
  id: string;
  label: string;
  chip: string;
  detail: string[];
  kind: string;
  time: string;
  status?: 'running' | 'complete' | 'failed' | 'recorded' | 'interrupted';
};
export default function ToolChips({ steps }: { steps: ToolStep[] }) {
  const [openRows, setOpenRows] = useState<Set<string>>(new Set());
  const list = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  useEffect(() => {
    if (list.current && followLatest.current) list.current.scrollTop = list.current.scrollHeight;
  }, [steps.length]);
  return (
    <div
      ref={list}
      onScroll={() => {
        const el = list.current;
        if (el) followLatest.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
      }}
      className="bui-tool-chips flex min-w-0 flex-col gap-1"
    >
      {steps.map((row) => {
        const open = openRows.has(row.id);
        const warning =
          row.status === 'failed' || ['error', 'tool_failure', 'warning'].includes(row.kind);
        const Icon =
          row.status === 'running'
            ? Loader2
            : warning
              ? AlertTriangle
              : row.kind === 'data'
                ? Database
                : row.kind === 'tool'
                  ? Search
                  : row.kind === 'complete'
                    ? Check
                    : FileSearch;
        return (
          <div key={row.id}>
            <button
              type="button"
              aria-expanded={open}
              onClick={() =>
                setOpenRows((current) => {
                  const next = new Set(current);
                  next.has(row.id) ? next.delete(row.id) : next.add(row.id);
                  return next;
                })
              }
              className={`group flex min-h-8 w-full min-w-0 items-center gap-2 rounded-control px-1 py-1 text-left transition-colors duration-100 hover:bg-hover-2 ${warning ? 'text-red' : 'text-ink-2'}`}
            >
              <Icon
                size={13}
                className={`shrink-0 ${row.status === 'running' ? 'spin' : ''}`}
                aria-hidden="true"
              />
              <span className="tool-label text-[12px]">{row.label}</span>
              {(row.chip || row.status) && (
                <span className="tool-chip rounded-chip bg-field px-1.5 py-0.5 text-[11px]">
                  {row.status
                    ? {
                        running: '执行中',
                        complete: '已完成',
                        failed: '未成功',
                        recorded: '已记录',
                        interrupted: '已中断',
                      }[row.status]
                    : row.chip}
                </span>
              )}
              <time className="ml-auto shrink-0 text-[10px] text-ink-2">{row.time}</time>
              <ChevronRight
                size={12}
                className="shrink-0"
                style={{ transform: open ? 'rotate(90deg)' : undefined }}
              />
            </button>
            {open && (
              <div className="mt-1 mb-2 ml-2 flex flex-col gap-1 border-l border-line py-1 pl-3.5 text-[12px] text-ink-2">
                {row.detail.length ? (
                  row.detail.map((text, index) => (
                    <p className="break-words" key={index}>
                      {text}
                    </p>
                  ))
                ) : (
                  <p>已记录此操作 · {row.time}</p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
