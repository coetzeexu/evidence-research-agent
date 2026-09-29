import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { expect, it } from 'vitest';

it('builds an offline browser runtime without Node environment reads', async () => {
  const result = await build({
    configFile: fileURLToPath(new URL('../../vite.report.config.ts', import.meta.url)),
    logLevel: 'silent',
    build: { write: false },
  });
  const outputs = Array.isArray(result) ? result : [result];
  const script = outputs
    .flatMap((output) => ('output' in output ? output.output : []))
    .flatMap((asset) => (asset.type === 'chunk' ? [asset.code] : []))
    .join('\n');

  expect(script.length).toBeGreaterThan(1000);
  // Test the generated artifact, not just its config: React's retained
  // process.env reads previously made the downloaded HTML blank in Chrome.
  expect(script).not.toMatch(/\bprocess\s*\.\s*env\b/);
}, 30_000);
