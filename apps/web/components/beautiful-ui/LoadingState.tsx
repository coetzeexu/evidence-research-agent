// Adapted from Beautiful UI primitives/LoadingState.tsx (MIT).
// Its pixel-grid wave and shimmering label represent real pending work; no demo timers/video.
export default function LoadingState({ label, elapsed }: { label: string; elapsed?: string }) {
  return (
    <div className="bui-loading" role="status">
      <span className="bui-loader-grid" aria-hidden="true">
        {Array.from({ length: 9 }, (_, i) => (
          <i
            key={i}
            style={{ animationDelay: `${((i % 3) + Math.abs(Math.floor(i / 3) - 1)) * 90}ms` }}
          />
        ))}
      </span>
      <span className="bui-shimmer">{label}</span>
      {elapsed && <time>{elapsed}</time>}
    </div>
  );
}
