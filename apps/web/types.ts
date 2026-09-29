export interface Spec {
  intent: 'event_study' | 'asset_comparison' | 'combined';
  title: string;
  symbols: string[];
  start: string;
  end: string;
  topics: string[];
  required_events?: string[];
  event_scope?: 'broad' | 'focused';
  benchmark: string;
  windows: number[];
  weights: number[];
  rebalance_months: number;
  cost_bps: number;
  initial_capital: number;
  outputs: string[];
  assumptions: string[];
}
export interface Bar {
  date: string;
  opened_at: string;
  closed_at: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adj_close: number;
  volume: number;
}
export interface Dataset {
  id: string;
  instrument: {
    symbol: string;
    name: string;
    currency: string;
    calendar: string;
    proxy_note?: string;
  };
  bars: Bar[];
  retrieved_at: string;
  source_url: string;
  warnings: string[];
  content_hash: string;
}
export interface Source {
  id: string;
  title: string;
  url: string;
  publisher: string;
  published_at?: string;
  retrieved_at: string;
  excerpt: string;
  status: string;
  content_hash: string;
}
export interface Event {
  id: string;
  title: string;
  date: string;
  summary: string;
  category: string;
  confidence: string;
  source_ids: string[];
  symbols: string[];
  uncertainty: string;
}
export interface Annotation {
  id: string;
  event_id: string;
  symbol: string;
  date: string;
  price: number;
  rating: string;
  confidence: string;
  direction: string;
  direction_window_days?: number | null;
  uncertainty: string;
  windows: Array<{
    days: number;
    complete: boolean;
    return: number | null;
    relative_return: number | null;
    start?: string;
    end?: string;
    start_closed_at?: string;
    end_closed_at?: string;
  }>;
}
export interface Run {
  id: string;
  title: string;
  status: string;
  mode: string;
  error?: string;
  created_at: string;
  parent_id?: string;
  prompt?: string;
  spec?: Spec;
  updated_at?: string;
}
export interface Trace {
  seq: number;
  kind: string;
  label: string;
  at: string;
  payload: Record<string, unknown>;
}
export interface ChatMessage {
  role: string;
  text: string;
  id?: string;
  status?: 'streaming' | 'complete' | 'interrupted';
}
export interface StreamSource {
  id: string;
  title: string;
  url: string;
  status?: string;
}
export interface Bundle {
  research?: {
    status: 'unassessed' | 'complete' | 'partial' | 'failed';
    text: string;
    questions: Array<{ id: string; question: string; status: string; gaps: string[] }>;
  } | null;
  id: string;
  created_at: string;
  mode: string;
  spec: Spec;
  method_version?: string;
  datasets: Record<string, Dataset>;
  sources: Source[];
  events: Event[];
  annotations: Annotation[];
  changes: Array<{
    id: string;
    symbol: string;
    date: string;
    type: string;
    return: number;
    event_ids: string[];
    confirmed_at: string;
    note?: string;
    associations?: Array<{
      event_id: string;
      lag_bars: number;
      reason: string;
      source_ids: string[];
    }>;
  }>;
  metrics: Array<Record<string, any>>;
  comparison: Record<string, any>;
  claims: Array<{
    id: string;
    text: string;
    kind: string;
    evidence_ids: string[];
    metric_ids: string[];
  }>;
  coverage: Array<Record<string, any>>;
  warnings: string[];
  disclosures: Array<{
    title: string;
    description: string;
    reason: string;
    limitations: string;
    url: string;
    verified_at: string;
  }>;
  review: Record<string, any>;
  quality?: {
    passed: boolean;
    requirements: Array<{ requirement: string; event_ids: string[]; status: string }>;
    periods: Array<{
      start: string;
      end: string;
      event_ids: string[];
      required: boolean;
      status: string;
    }>;
    repair_actions: Array<{ kind: string; query: string; reason: string }>;
    data_gaps: string[];
    changes: number;
    associated_changes: number;
    note: string;
  };
}

export const pct = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(value)
    ? '—'
    : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`;
export const safeUrl = (url: string) => {
  try {
    const parsed = new URL(url);
    return ['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password
      ? url
      : undefined;
  } catch {
    return undefined;
  }
};

export function linkCitations(text: string, bundle: Bundle) {
  const links = new Map([
    ...bundle.sources.map((s) => [s.id, s.url] as const),
    ...Object.values(bundle.datasets).map((d) => [d.id, d.source_url] as const),
  ]);
  return text.replace(/\[([^\]\n]+)\](?!\()/g, (full, id) => {
    const url = links.get(id);
    return url && safeUrl(url) ? `[${id}](${url})` : full;
  });
}
