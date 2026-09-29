import { lazy, Suspense } from 'react';
import type { ComponentProps } from 'react';
import type { Chart as ChartComponent } from './Chart';

const LoadedChart = lazy(() => import('./Chart').then((module) => ({ default: module.Chart })));

export function Chart(props: ComponentProps<typeof ChartComponent>) {
  return (
    <Suspense
      fallback={
        <div role="status" style={{ height: props.height || 400 }}>
          正在加载图表…
        </div>
      }
    >
      <LoadedChart {...props} />
    </Suspense>
  );
}
