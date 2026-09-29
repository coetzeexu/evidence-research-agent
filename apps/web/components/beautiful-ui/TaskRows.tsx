// Adapted from Beautiful UI by Shane Levine (MIT). See LICENSE and README.md.
// Production state is supplied by the research event stream; no demo timers.
import { useState, type ReactNode } from 'react';

function SpinnerRing({ active, children }: { active?: boolean; children?: ReactNode }) {
  const size = 24,
    stroke = 2;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        className="absolute inset-0"
        style={active ? { animation: 'spin 1.1s linear infinite' } : undefined}
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--line)"
          strokeWidth={stroke}
        />
        {active && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--ink-3)"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${c * 0.28} ${c * 0.72}`}
          />
        )}
      </svg>
      <span className="relative text-[10.5px] font-semibold tabular-nums text-ink">{children}</span>
    </span>
  );
}

function Badge({ tone, children }: { tone: 'red' | 'green'; children: ReactNode }) {
  return (
    <span
      className={`flex size-5.5 shrink-0 items-center justify-center rounded-full text-white
        ${tone === 'red' ? 'bg-red' : 'bg-green'}`}
      style={{ animation: 'pop-in 300ms cubic-bezier(0.23,1,0.32,1) both' }}
    >
      {children}
    </span>
  );
}

const XIcon = (
  <svg
    width="12"
    height="12"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="3.5"
    strokeLinecap="round"
  >
    <path d="M18 6L6 18M6 6l12 12" />
  </svg>
);
const CheckIcon = (
  <svg
    width="13"
    height="13"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="3.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M20 6L9 17l-5-5" />
  </svg>
);
export type TaskStatus = 'pending' | 'running' | 'done' | 'failed' | 'paused' | 'cancelled';
export type TaskRow = {
  key: string;
  label: string;
  amount: string;
  status: TaskStatus;
  step: number;
  details: ReactNode;
};
const statusLabels: Record<TaskStatus, string> = {
  pending: '等待',
  running: '进行中',
  done: '完成',
  failed: '失败',
  paused: '待补充',
  cancelled: '已停止',
};
export default function TaskRows({ rows }: { rows: TaskRow[] }) {
  const [manualOpen, setManualOpen] = useState<Record<string, boolean>>({});
  const badgeFor = (row: TaskRow) => {
    if (row.status === 'done') return <Badge tone="green">{CheckIcon}</Badge>;
    if (row.status === 'failed') return <Badge tone="red">{XIcon}</Badge>;
    return <SpinnerRing active={row.status === 'running'}>{row.step}</SpinnerRing>;
  };
  return (
    <div className="bui-task-rows flex w-full flex-col gap-2" aria-label="研究执行步骤">
      {rows.map((row) => {
        const open = manualOpen[row.key] ?? row.status === 'running';
        return (
          <div
            key={row.key}
            className="self-stretch overflow-hidden bg-surface shadow-card transition-[border-radius,background-color] duration-200 hover:bg-inset"
            style={{ borderRadius: open ? 14 : 22 }}
          >
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setManualOpen((current) => ({ ...current, [row.key]: !open }))}
              className="flex min-h-11 w-full items-center gap-2.5 px-2.5 py-2 text-left"
            >
              <span className="flex size-6 shrink-0 items-center justify-center" aria-hidden="true">
                {badgeFor(row)}
              </span>
              <span className="min-w-0 flex-1 text-[13px] font-medium text-ink">{row.label}</span>
              <span className="text-[12px] text-ink-2 tabular-nums">{row.amount}</span>
              <span className={`task-status ${row.status}`}>{statusLabels[row.status]}</span>
              <svg
                aria-hidden="true"
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="shrink-0 text-ink-3 transition-transform duration-200"
                style={{ transform: open ? 'rotate(180deg)' : undefined }}
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {open && (
              <div className="mb-3 grid grid-cols-[24px_1fr] gap-2.5 px-2.5">
                <span aria-hidden className="mx-auto h-full w-px bg-line" />
                <div className="min-w-0">{row.details}</div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
