export const palette = ['#3d7668', '#c19554', '#7188ab', '#b27882', '#8c83ac'];
// A single scale is shared by chart marks, filters, table badges and evidence cards.
const reactions = {
  高: { color: '#b45309', tint: '#fff1db', size: 40, short: '高' },
  中: { color: '#2563eb', tint: '#eff6ff', size: 34, short: '中' },
  低: { color: '#64748b', tint: '#f1f5f9', size: 28, short: '低' },
  不可评估: { color: '#78716c', tint: '#fafaf9', size: 28, short: '?' },
};
export function reactionStyle(rating) {
  return reactions[rating] || reactions['不可评估'];
}
const base = {
  animation: false,
  backgroundColor: 'transparent',
  color: palette,
  textStyle: { fontFamily: 'Arial, PingFang SC, Noto Sans CJK SC, sans-serif', color: '#747b79' },
  tooltip: {
    trigger: 'axis',
    renderMode: 'richText',
    backgroundColor: '#fff',
    borderColor: '#e4e8e5',
  },
  grid: { left: 64, right: 30, top: 38, bottom: 52 },
  legend: {
    top: 2,
    right: 16,
    icon: 'roundRect',
    itemWidth: 15,
    itemHeight: 3,
    textStyle: { color: '#6b7470' },
  },
};
const axis = {
  axisLine: { lineStyle: { color: '#e5e9e6' } },
  axisTick: { show: false },
  axisLabel: { color: '#88918c', fontSize: 10 },
  splitLine: { lineStyle: { color: '#eff1ee', type: 'dashed' } },
};

export function candleOption(bundle, symbol, options = {}) {
  const bars = bundle.datasets[symbol].bars.filter(
    (b) => b.date >= bundle.spec.start && b.date <= bundle.spec.end,
  );
  const annotations = bundle.annotations.filter(
    (a) => a.symbol === symbol && (!options.rating || a.rating === options.rating),
  );
  return {
    ...base,
    legend: { show: false },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 70, right: 34, top: 32, height: '64%' },
      { left: 70, right: 34, top: '77%', height: '11%' },
    ],
    xAxis: [
      {
        ...axis,
        type: 'category',
        data: bars.map((b) => b.date),
        boundaryGap: true,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      {
        ...axis,
        type: 'category',
        gridIndex: 1,
        data: bars.map((b) => b.date),
        boundaryGap: true,
        splitLine: { show: false },
        axisLabel: { fontSize: 10, formatter: (v) => v.slice(0, 7) },
      },
    ],
    yAxis: [
      { ...axis, scale: true, axisLabel: { formatter: (v) => '$' + v.toLocaleString('en-US') } },
      {
        ...axis,
        gridIndex: 1,
        splitNumber: 1,
        axisLabel: { formatter: (v) => (v / 1e6).toFixed(0) + 'M' },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        bottom: 3,
        height: 18,
        borderColor: 'transparent',
        fillerColor: '#dce8e133',
        handleSize: '80%',
        dataBackground: { lineStyle: { color: '#cad7cf' }, areaStyle: { color: '#edf1eb' } },
        selectedDataBackground: {
          lineStyle: { color: '#759d8c' },
          areaStyle: { color: '#dbe7dc' },
        },
      },
    ],
    series: [
      {
        name: symbol,
        type: 'candlestick',
        data: bars.map((b) => [b.open, b.close, b.low, b.high]),
        itemStyle: {
          color: '#579982',
          color0: '#c7776c',
          borderColor: '#579982',
          borderColor0: '#c7776c',
        },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: bars.map((b) => ({
          value: b.volume,
          itemStyle: { color: b.close >= b.open ? '#b7d0c5' : '#e2c4bc' },
        })),
      },
      {
        name: '已核验事件',
        type: 'scatter',
        symbol: 'pin',
        z: 6,
        data: annotations.map((a, index) => {
          const style = reactionStyle(a.rating);
          const sameDate = annotations.filter((other) => other.date === a.date);
          const ordinal = annotations
            .slice(0, index)
            .filter((other) => other.date === a.date).length;
          return {
            value: [a.date, a.price],
            eventId: a.event_id,
            rating: a.rating,
            direction: a.direction,
            confidence: a.confidence,
            window:
              a.windows?.find((w) => w.days === a.direction_window_days) ||
              a.windows?.find((w) => w.days === 5 && w.complete) ||
              a.windows?.find((w) => w.complete),
            symbolSize: style.size,
            symbolOffset:
              sameDate.length > 1 ? [(ordinal - (sameDate.length - 1) / 2) * 26, 0] : [0, 0],
            itemStyle: { color: style.color, opacity: 1, borderColor: '#fff', borderWidth: 1 },
            label: {
              show: true,
              formatter: style.short,
              color: '#fff',
              fontSize: 11,
              fontWeight: 'bold',
            },
            name: bundle.events.find((e) => e.id === a.event_id)?.title || a.date,
          };
        }),
        emphasis: { scale: 1.15 },
        tooltip: {
          trigger: 'item',
          renderMode: 'richText',
          confine: true,
          formatter: (p) => {
            const d = p.data,
              w = d.window;
            const relative = w?.relative_return;
            return `${d.name}\n${d.value[0]} · 市场反应：${d.rating}\n相对基准方向：${d.direction}${w ? `（${w.days} 根日线）` : ''}\n相对收益：${relative == null ? '不可评估' : `${relative >= 0 ? '+' : ''}${(relative * 100).toFixed(2)}%`}\n关联可信度：${{ high: '高', medium: '中', low: '低' }[d.confidence] || '未评估'}\n点击查看原始证据`;
          },
        },
      },
      {
        name: '异动候选关联',
        type: 'scatter',
        symbol: 'diamond',
        symbolSize: 12,
        z: 7,
        data: bundle.changes
          .filter((c) => c.symbol === symbol)
          .flatMap((c) =>
            (c.associations || [])
              .filter(
                (link) =>
                  link.lag_bars > 0 && annotations.some((a) => a.event_id === link.event_id),
              )
              .map((link) => ({
                value: [c.date, bars.find((b) => b.date === c.date)?.close],
                eventId: link.event_id,
                name: bundle.events.find((e) => e.id === link.event_id)?.title,
                lag: link.lag_bars,
                reason: link.reason,
              })),
          ),
        itemStyle: { color: '#64748b', borderColor: '#fff', borderWidth: 1 },
        tooltip: {
          trigger: 'item',
          renderMode: 'richText',
          confine: true,
          formatter: (p) =>
            `${p.data.value[0]} · 候选关联\n${p.data.name}\n公开后第 ${p.data.lag} 根日线\n${p.data.reason}\n点击查看证据，不代表因果`,
        },
      },
      {
        name: '行情变化',
        type: 'scatter',
        symbol: 'diamond',
        symbolSize: 6,
        z: 5,
        data: bundle.changes
          .filter((c) => c.symbol === symbol && c.event_ids.length === 0)
          .map((c) => ({
            value: [c.date, bars.find((b) => b.date === c.date)?.close],
            name: c.type,
          })),
        itemStyle: { color: '#b5b7af' },
        tooltip: {
          trigger: 'item',
          renderMode: 'richText',
          formatter: (p) => p.data.name + ' · 暂无匹配事件',
        },
      },
    ],
  };
}

export function comparisonOption(bundle, mode = 'normalized') {
  const series = bundle.comparison.series || [];
  return {
    ...base,
    xAxis: {
      ...axis,
      type: 'category',
      data: series[0]?.dates || [],
      boundaryGap: false,
      axisLabel: { fontSize: 10, formatter: (v) => v.slice(0, 7) },
      splitLine: { show: false },
    },
    yAxis: {
      ...axis,
      type: 'value',
      scale: true,
      axisLabel: {
        formatter: mode === 'drawdown' ? (v) => (v * 100).toFixed(0) + '%' : (v) => Math.round(v),
      },
    },
    series: series.map((s, i) => ({
      name: s.symbol,
      type: 'line',
      data: s[mode],
      showSymbol: false,
      lineStyle: { width: 2.5, color: palette[i] },
      connectNulls: false,
      areaStyle: mode === 'drawdown' ? { opacity: 0.07 } : undefined,
    })),
    dataZoom: [
      { type: 'inside' },
      { type: 'slider', height: 15, bottom: 0, borderColor: 'transparent' },
    ],
  };
}

export function heatmapOption(bundle) {
  const symbols = bundle.spec.symbols;
  return {
    ...base,
    legend: { show: false },
    grid: { left: 70, right: 48, top: 24, bottom: 80 },
    tooltip: {
      trigger: 'item',
      renderMode: 'richText',
      formatter: (p) =>
        `${symbols[p.value[0]]} / ${symbols[p.value[1]]}: ${p.value[2]?.toFixed(2)}`,
    },
    xAxis: { ...axis, type: 'category', data: symbols, splitArea: { show: false } },
    yAxis: { ...axis, type: 'category', data: symbols },
    visualMap: {
      min: -1,
      max: 1,
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 8,
      inRange: { color: ['#d6b2a2', '#f6f6f0', '#659b88'] },
    },
    series: [
      {
        type: 'heatmap',
        data: (bundle.comparison.correlations || []).map((c) => [
          symbols.indexOf(c.x),
          symbols.indexOf(c.y),
          c.value,
        ]),
        label: {
          show: true,
          formatter: (p) => p.value[2]?.toFixed(2),
          fontSize: 20,
          color: '#344b42',
        },
        itemStyle: { borderWidth: 5, borderColor: '#fff' },
      },
    ],
  };
}

export function portfolioOption(bundle) {
  const rows = bundle.comparison.backtest?.rows || [],
    approximation = bundle.comparison.formula_backtest?.rows || [];
  return {
    ...base,
    xAxis: {
      ...axis,
      type: 'category',
      data: rows.map((r) => r.date),
      boundaryGap: false,
      axisLabel: { formatter: (v) => v.slice(0, 7) },
      splitLine: { show: false },
    },
    yAxis: {
      ...axis,
      type: 'value',
      scale: true,
      axisLabel: { formatter: (v) => (v / 1000).toFixed(0) + 'k' },
    },
    series: [
      {
        name: '下一开盘执行',
        type: 'line',
        showSymbol: false,
        data: rows.map((r) => r.nav),
        lineStyle: { width: 2.5 },
      },
      {
        name: '月度配置近似',
        type: 'line',
        showSymbol: false,
        data: approximation.map((r) => r.nav),
        lineStyle: { width: 1.5, type: 'dashed' },
      },
    ],
  };
}
