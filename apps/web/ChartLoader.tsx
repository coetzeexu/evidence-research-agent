import { lazy, Suspense } from 'react';
import type { ComponentProps } from 'react';
import type { Chart as ChartComponent } from './Chart';
import './chart-loading.css';

const LoadedChart = lazy(() => import('./Chart').then((module) => ({ default: module.Chart })));

export function Chart(props: ComponentProps<typeof ChartComponent>) {
  return (
    <Suspense
      fallback={
        <div
          className="chart-loading"
          role="status"
          aria-busy="true"
          style={{ height: props.height ?? 400 }}
        >
          <span>正在加载图表…</span>
          <div className="chart-loading-area" aria-hidden="true" />
        </div>
      }
    >
      <LoadedChart {...props} />
    </Suspense>
  );
}
