import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ResearchView, EvidencePanel } from './ResearchView';
import type { Bundle } from './types';
import './styles.css';

function OfflineReport() {
  const bundle = JSON.parse(document.getElementById('report-data')!.textContent!) as Bundle;
  const [eventId, setEventId] = useState<string | null>(null);
  return (
    <div className="offline-shell">
      <div className="offline-banner">
        <span className="brand-mark">e</span>
        <strong>Evidence</strong>
        <span>可交互研究报告</span>
        <small>本地快照 · 来源可点击复核</small>
      </div>
      <main className={eventId ? 'report-layout with-evidence' : 'report-layout'}>
        <ResearchView bundle={bundle} onSelect={setEventId} />
        {eventId && (
          <aside className="inspector">
            <EvidencePanel bundle={bundle} eventId={eventId} onClose={() => setEventId(null)} />
          </aside>
        )}
      </main>
    </div>
  );
}
createRoot(document.getElementById('root')!).render(<OfflineReport />);
