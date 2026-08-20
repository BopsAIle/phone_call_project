/**
 * Bundles the browser dev client into public/assets/.
 *
 * A Node script rather than a shell one-liner in package.json: the build ends
 * with a `Buffer` check over the output (see below), and npm scripts run under
 * cmd.exe on Windows where `grep` does not exist.
 *
 *   node scripts/build-client.mjs [--watch]
 */
import { build, context } from 'esbuild';
import { readFile } from 'fs/promises';

const OUT_DIR = 'public/assets';

/**
 * The worklet is a separate entry point on purpose. AudioWorklets run in their
 * own global scope and cannot import from the main bundle, so it has to be a
 * standalone file that `audioWorklet.addModule` can fetch.
 */
const ENTRY_POINTS = ['client/main.ts', 'client/capture-worklet.ts'];

const options = {
  entryPoints: ENTRY_POINTS,
  outdir: OUT_DIR,
  bundle: true,
  format: 'esm',
  target: 'es2022',
  platform: 'browser',
  sourcemap: true,
  logLevel: 'info',
};

/**
 * The main bundle imports src/audio/mulaw.codec.ts, which also exports
 * `encodeMulaw` — and that one allocates with `Buffer.allocUnsafe`, which does
 * not exist in a browser. We rely on esbuild tree-shaking it away because
 * client/main.ts imports only `pcm16ToMulaw` and `decodeMulaw`.
 *
 * Nothing enforces that. If it ever regresses the page dies with
 * `Buffer is not defined` at module load — before any of our code runs, so the
 * console says nothing about audio and the failure looks like a broken page
 * rather than a bad import. Cheaper to assert it here every build.
 */
async function assertNoNodeGlobals() {
  const bundle = await readFile(`${OUT_DIR}/main.js`, 'utf8');

  if (/\bBuffer\b/.test(bundle)) {
    throw new Error(
      `${OUT_DIR}/main.js references Buffer.\n` +
        'Something now pulls a Node-only path out of mulaw.codec.ts — most ' +
        'likely an import of encodeMulaw, which esbuild can no longer drop.',
    );
  }
}

if (process.argv.includes('--watch')) {
  const ctx = await context(options);
  await ctx.watch();
  console.log(`watching client/ → ${OUT_DIR}`);
} else {
  await build(options);
  await assertNoNodeGlobals();
  console.log(`built client/ → ${OUT_DIR}`);
}
