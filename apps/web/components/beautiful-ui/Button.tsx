// Adapted from Beautiful UI's atoms/Button.tsx (MIT); see LICENSE and README.md.
// Use local variant maps instead of adding cva/clsx/tailwind-merge dependencies.
import type { ButtonHTMLAttributes } from 'react';

const variants = {
  primary: 'bg-ink text-canvas hover:opacity-90 shadow-[inset_0_1px_0_rgba(255,255,255,0.14)]',
  secondary: 'bg-surface text-ink shadow-btn hover:bg-inset aria-expanded:bg-hover',
  quiet: 'text-ink hover:bg-hover',
};
export function Button({
  variant = 'secondary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof variants }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-full px-4 py-[9px] text-[13px] leading-none font-medium select-none transition-[transform,background-color,opacity] duration-150 ease-out active:scale-[0.96] disabled:opacity-50 disabled:pointer-events-none ${variants[variant]} ${className}`}
      {...props}
    />
  );
}
