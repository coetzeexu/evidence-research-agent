// Adapted from the composer in Beautiful UI's ChatComposer.tsx (MIT).
// Controlled textarea, IME-safe submission and real pending state replace the demo.
import { useId, useRef, type ReactNode, type Ref } from 'react';
import { ArrowUp, Loader2 } from 'lucide-react';
import { Button } from './Button';

export default function ChatComposer({
  value,
  onChange,
  onSend,
  placeholder,
  label,
  hint,
  busy = false,
  busyLabel = '正在提交',
  disabled = false,
  inputRef,
  children,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  placeholder: string;
  label: string;
  hint?: string;
  busy?: boolean;
  busyLabel?: string;
  disabled?: boolean;
  inputRef?: Ref<HTMLTextAreaElement>;
  children?: ReactNode;
}) {
  const hintId = useId();
  const composing = useRef(false);
  const canSend = !!value.trim() && !busy && !disabled;
  return (
    <form
      className="bui-composer flex flex-col gap-2 rounded-control border border-line bg-field p-3 shadow-[0_1px_2px_rgba(0,0,0,0.035)] transition-[border-color,box-shadow] duration-150 focus-within:border-line-strong"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSend();
      }}
    >
      {children}
      <textarea
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={() => {
          composing.current = false;
        }}
        onKeyDown={(e) => {
          if (
            e.key === 'Enter' &&
            !e.shiftKey &&
            !e.nativeEvent.isComposing &&
            !composing.current &&
            e.keyCode !== 229
          ) {
            e.preventDefault();
            if (canSend) onSend();
          }
        }}
        placeholder={placeholder}
        aria-label={placeholder}
        aria-describedby={hint ? hintId : undefined}
        rows={3}
        disabled={disabled || busy}
        className="w-full resize-none bg-transparent text-[14px] leading-relaxed text-ink outline-none placeholder:text-ink-3"
      />
      <div className="composer-bottom flex items-center justify-between gap-3">
        {hint && <span id={hintId}>{hint}</span>}
        <Button type="submit" variant="primary" disabled={!canSend} aria-label={label}>
          {busy ? <Loader2 size={14} className="spin" /> : <ArrowUp size={14} />}
          {busy ? busyLabel : label}
        </Button>
      </div>
    </form>
  );
}
