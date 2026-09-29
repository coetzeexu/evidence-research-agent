import { useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { CandlestickChart, BarChart, LineChart, ScatterChart, HeatmapChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  VisualMapComponent,
  MarkLineComponent,
  AriaComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  CandlestickChart,
  BarChart,
  LineChart,
  ScatterChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  VisualMapComponent,
  MarkLineComponent,
  AriaComponent,
  CanvasRenderer,
]);

export function Chart({
  option,
  height = 400,
  onEvent,
}: {
  option: Record<string, any>;
  height?: number;
  onEvent?: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const click = useRef(onEvent);
  click.current = onEvent;
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' });
    chart.setOption({ ...option, aria: { enabled: true } });
    chart.on('click', (params: any) => {
      if (params.data?.eventId) click.current?.(params.data.eventId);
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option]);
  return (
    <div
      ref={ref}
      className="chart"
      style={{ height }}
      role="img"
      aria-label="可交互研究图表，可用下方数据表复核"
    />
  );
}
