import fs from 'node:fs';
import path from 'node:path';
import * as echarts from 'echarts';
import { Resvg } from '@resvg/resvg-js';
import { candleOption, comparisonOption, portfolioOption } from '../packages/charts/options.mjs';

const [input, output] = process.argv.slice(2);
if (!input || !output)
  throw new Error('Usage: node tools/render-charts.mjs bundle.json output-dir');
const bundle = JSON.parse(fs.readFileSync(input, 'utf8'));
fs.mkdirSync(output, { recursive: true });
const options = { market: candleOption(bundle, bundle.spec.symbols[0]) };
if (bundle.comparison.series?.length) {
  options.comparison = comparisonOption(bundle);
  options.drawdown = comparisonOption(bundle, 'drawdown');
  options.portfolio = portfolioOption(bundle);
}
for (const [name, option] of Object.entries(options)) {
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 1400, height: 600 });
  option.backgroundColor = '#ffffff';
  chart.setOption(option);
  const svg = chart.renderToSVGString();
  fs.writeFileSync(path.join(output, `${name}.svg`), svg);
  const image = new Resvg(svg, {
    font: { loadSystemFonts: true, defaultFontFamily: 'PingFang SC' },
  })
    .render()
    .asPng();
  fs.writeFileSync(path.join(output, `${name}.png`), image);
  chart.dispose();
}
