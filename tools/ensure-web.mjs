// Rebuild only when the dependency lock, source tree, or generated assets change.
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = fileURLToPath(new URL('../', import.meta.url));
const sha = (value) => createHash('sha256').update(value).digest('hex');
function command(args) {
  const result = spawnSync(process.platform === 'win32' ? 'npm.cmd' : 'npm', args, {
    cwd: root,
    stdio: 'inherit',
    shell: process.platform === 'win32',
  });
  if (result.status !== 0) process.exit(result.status || 1);
}
const lockHash = sha(readFileSync(resolve(root, 'package-lock.json')));
const installed = resolve(root, 'node_modules/.evidence-lock');
if (!existsSync(installed) || readFileSync(installed, 'utf8') !== lockHash) {
  command(['ci']);
  writeFileSync(installed, lockHash);
}
function files(path) {
  return readdirSync(resolve(root, path), { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? files(`${path}/${entry.name}`) : [`${path}/${entry.name}`],
  );
}
const inputs = [
  ...files('apps'),
  ...files('packages'),
  'package.json',
  'package-lock.json',
  'index.html',
  'tsconfig.json',
  'vite.config.ts',
  'vite.report.config.ts',
].sort();
const buildHash = sha(
  Buffer.concat(
    inputs.map((name) =>
      Buffer.concat([
        Buffer.from(`${name}\0`),
        readFileSync(resolve(root, name)),
        Buffer.from('\0'),
      ]),
    ),
  ),
);
const stamp = resolve(root, 'dist/.source-hash');
const required = ['dist/web/index.html', 'dist/report/report.js', 'dist/report/report.css'];
if (
  !existsSync(stamp) ||
  readFileSync(stamp, 'utf8') !== buildHash ||
  required.some((p) => !existsSync(resolve(root, p)))
) {
  command(['run', 'build']);
  writeFileSync(stamp, buildHash);
}
