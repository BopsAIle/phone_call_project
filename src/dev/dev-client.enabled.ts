/**
 * Whether the dev surface — `GET /dev` and the bundle it loads — exists at all.
 *
 * Read from `process.env` rather than `ConfigService` because `app.module.ts`
 * needs the answer while the module graph is being built, which is before DI
 * exists. That is the standard Nest idiom for a module that must not be
 * registered at all in production.
 *
 * `main.ts` calls the same function to gate the static assets. Two separate
 * checks would drift, and the failure mode is quiet: `/dev` would 404 in
 * production while `/dev/assets/main.js` carried on serving the bundle.
 */
export function isDevClientEnabled(): boolean {
  return process.env.NODE_ENV !== 'production';
}

/** Where `useStaticAssets` mounts the generated bundle. */
export const DEV_ASSETS_PREFIX = '/dev/assets';
