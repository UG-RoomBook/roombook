/** Keep only a payload digest and random retry key in this tab; never store admin form contents. */
export async function adminRetryKey(user: string, intent: unknown, fallback: string) {
  const bytes = new TextEncoder().encode(JSON.stringify(intent));
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('');
  const storageKey = `roombook.admin.retry.${user}.${digest}`;
  let key = fallback;
  try {
    const existing = sessionStorage.getItem(storageKey);
    if (existing && /^[0-9a-f-]{36}$/.test(existing)) key = existing;
    sessionStorage.setItem(storageKey, key);
  } catch {
    /* In-memory key still protects retries when tab storage is unavailable. */
  }
  return {
    key,
    clear: () => {
      try {
        sessionStorage.removeItem(storageKey);
      } catch {
        /* Storage unavailable. */
      }
    },
  };
}
