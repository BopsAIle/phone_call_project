/**
 * Races a promise against a timer.
 *
 * Needed wherever we talk to Postgres, because a stopped container does not
 * refuse connections quickly — the socket hangs until the OS TCP timeout.
 * Setting `connect_timeout` in DATABASE_URL helps the driver open new
 * connections but does not bound one that was established and then severed.
 */
export function withTimeout<T>(
  work: PromiseLike<T>,
  ms: number,
  label: string,
): Promise<T> {
  let timer: NodeJS.Timeout;

  const expiry = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () => reject(new Error(`${label} timed out after ${ms}ms`)),
      ms,
    );
  });

  return Promise.race([work, expiry]).finally(() => clearTimeout(timer));
}
