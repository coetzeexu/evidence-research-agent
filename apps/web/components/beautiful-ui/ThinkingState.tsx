// Adapted from Beautiful UI primitives/ThinkingState.tsx (MIT).
// Dynamic activity grouping follows the local WorkAgentActivity interaction pattern.
// Open state is user-controlled once changed; arriving tokens never force it open.
import { useId, useState, type ReactNode } from 'react';
import { AlertTriangle, Check, ChevronRight, Loader2, Pause } from 'lucide-react';

export type ActivityState = 'running' | 'complete' | 'failed' | 'paused';
export default function ThinkingState({
  title,
  state,
  autoExpand,
  meta,
  children,
}: {
  title: string;
  state: ActivityState;
  autoExpand?: boolean;
  meta?: string;
  children: ReactNode;
}) {
  const id = useId();
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const open =
    manualOpen ?? autoExpand ?? (state === 'running' || state === 'failed' || state === 'paused');
  const Icon =
    state === 'running'
      ? Loader2
      : state === 'failed'
        ? AlertTriangle
        : state === 'paused'
          ? Pause
          : Check;
  return (
    <section className={`bui-thinking ${state}`}>
      <button
        type="button"
        className="activity-header"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setManualOpen(!open)}
      >
        <Icon size={15} className={state === 'running' ? 'spin' : ''} aria-hidden="true" />
        <span className={state === 'running' ? 'bui-shimmer' : ''}>{title}</span>
        {meta && <small>{meta}</small>}
        <ChevronRight size={14} className={open ? 'expanded' : ''} aria-hidden="true" />
      </button>
      <div id={id} hidden={!open} className="activity-body">
        {open && children}
      </div>
    </section>
  );
}
