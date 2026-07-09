/**
 * Short-lived, scope-limited "stream" tokens for URL-embedded auth.
 *
 * `<img>` and `EventSource` can't send an Authorization header, so those URLs
 * carry the token as a query param — which leaks into proxy/access logs and
 * browser history. Putting the full 24h session token there is dangerous; this
 * mints a minutes-long, GET-only, image/SSE-scoped token instead (see
 * POST /api/auth/stream-token + AuthMiddleware STREAM_PATH_PREFIXES).
 *
 * The token is refreshed PROACTIVELY (a timer set for just before each expiry)
 * so it never lapses while the tab is open — otherwise image URLs would be
 * built with no token during the gap and 401. Subscribers (useStreamToken) are
 * notified on every change so image grids re-render with a valid token.
 */

const TOKEN_STORAGE_KEY = 'chub-auth-token';
const SKEW_MS = 30_000; // refresh this long before expiry

let cached = null; // { token: string, expMs: number }
let inflight = null;
let refreshTimer = null;
// null = unknown, true = auth on (token required), false = auth not configured
// (the /stream-token route is open, so image/SSE URLs need no token at all).
let authConfigured = null;
const listeners = new Set();

function fullToken() {
    try {
        return localStorage.getItem(TOKEN_STORAGE_KEY) || '';
    } catch {
        return '';
    }
}

function fresh() {
    return cached && cached.expMs - Date.now() > SKEW_MS ? cached.token : '';
}

function notify() {
    listeners.forEach(cb => cb());
}

/** Subscribe to stream-token changes; returns an unsubscribe fn. */
export function subscribeStreamToken(cb) {
    listeners.add(cb);
    return () => listeners.delete(cb);
}

/** The currently cached token ('' if none yet / cleared). */
export function streamTokenSnapshot() {
    return (cached && cached.token) || '';
}

/**
 * True once we've confirmed auth is NOT configured (the /stream-token endpoint
 * returned an empty token on a successful response). In that state the image /
 * SSE routes are open, so callers should build token-less URLs instead of
 * waiting for a token that will never arrive. Returns false while unknown or
 * while auth is on — so a blank placeholder is shown until a real token lands
 * (avoiding a 401 flash) rather than firing a token-less request that 401s.
 */
export function streamAuthDisabled() {
    return authConfigured === false;
}

function scheduleProactiveRefresh(ttlMs) {
    if (refreshTimer) clearTimeout(refreshTimer);
    // Refresh SKEW before expiry so the token never actually lapses. Force a
    // refetch by clearing `cached` first (ensureStreamToken short-circuits while
    // fresh, so the old interval-based refresh never actually renewed anything).
    const delay = Math.max(5_000, ttlMs - SKEW_MS);
    refreshTimer = setTimeout(() => {
        cached = null;
        ensureStreamToken();
    }, delay);
}

/** Fetch (or reuse) a valid stream token. Concurrent callers share one request. */
export async function ensureStreamToken() {
    const current = fresh();
    if (current) return current;
    // Auth confirmed off: the token is always empty and the route is open, so
    // stop re-hitting /stream-token on every render — there is nothing to mint.
    if (authConfigured === false) return '';
    if (!inflight) {
        const jwt = fullToken();
        inflight = fetch('/api/auth/stream-token', {
            method: 'POST',
            headers: jwt ? { Authorization: `Bearer ${jwt}` } : {},
        })
            .then(r => (r.ok ? r.json() : null))
            .then(d => {
                const token = d?.data?.token || '';
                const ttl = (d?.data?.expires_in || 0) * 1000;
                // A successful (200) response resolves the auth state: a
                // non-empty token means auth is on; an empty token means auth
                // is not configured (the route is open). A failed response
                // (null) is an auth-on 401/expired-JWT case, so leave the state
                // unchanged rather than mislabelling it as "not configured".
                if (d) authConfigured = token !== '';
                cached = token ? { token, expMs: Date.now() + ttl } : null;
                if (cached) scheduleProactiveRefresh(ttl);
                notify();
                return token;
            })
            .catch(() => '')
            .finally(() => {
                inflight = null;
            });
    }
    return inflight;
}

/**
 * Synchronous accessor for building `<img src>` during render: returns the
 * cached stream token, kicking off a refresh when missing/stale. Prefetched on
 * auth (see AuthContext) and kept warm by the proactive refresh above, so it's
 * ready before image grids render; components using useStreamToken re-render
 * once it arrives.
 */
export function streamTokenParam() {
    const current = fresh();
    if (!current && authConfigured !== false) ensureStreamToken();
    return current;
}

export function clearStreamToken() {
    cached = null;
    inflight = null;
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = null;
    notify();
}
