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
const RETRY_BASE_MS = 30_000;
const RETRY_MAX_MS = 300_000;

let cached = null; // { token: string, expMs: number }
let inflight = null;
let refreshTimer = null;
// null = unknown, true = auth on (token required), false = auth not configured
// (the /stream-token route is open, so image/SSE URLs need no token at all).
let authConfigured = null;
// Gate re-entry after a failed mint — see the loop note in ensureStreamToken.
let retryAfterMs = 0;
let retryDelayMs = RETRY_BASE_MS;
// The JWT a terminal 401 was seen on; retrying can't succeed until it changes.
let rejectedJwt = null;
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

/**
 * Mirror the 401 handling in core.js (this module uses a raw fetch, so it never
 * reaches that handler): a dead session must land on /login rather than leave
 * the app rendering an error it can't recover from.
 */
function handleAuthFailure(status, body) {
    const code = body?.error_code;
    if (status !== 401 || (code !== 'AUTH_REQUIRED' && code !== 'AUTH_TOKEN_INVALID')) {
        return;
    }
    rejectedJwt = fullToken();
    try {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
    } catch {
        /* noop */
    }
    if (window.location.pathname !== '/login') {
        window.location.href = '/login';
    }
}

/**
 * True while the last failure was a handled 401 and no new credential has
 * arrived. Retrying then cannot succeed, and AuthContext keeps a 4-minute
 * interval alive on /login (where handleAuthFailure does not navigate), so
 * without this the timers mint forever against a cleared session.
 */
function terminalAuthFailure() {
    if (rejectedJwt === null) return false;
    const jwt = fullToken();
    if (jwt && jwt !== rejectedJwt) {
        rejectedJwt = null;
        return false;
    }
    return true;
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

// One bounded retry after a failed mint, so a transient backend blip self-heals
// instead of leaving images token-less until the next unrelated re-render.
function scheduleRetry(delayMs) {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
        retryAfterMs = 0;
        ensureStreamToken();
    }, delayMs);
}

/** Fetch (or reuse) a valid stream token. Concurrent callers share one request. */
export async function ensureStreamToken() {
    const current = fresh();
    if (current) return current;
    // Auth confirmed off: the token is always empty and the route is open, so
    // stop re-hitting /stream-token on every render — there is nothing to mint.
    if (authConfigured === false) return '';
    // A failed mint must NOT re-arm on the next render: notify() re-renders every
    // subscriber, each rebuilt image URL calls streamTokenParam() -> back in here,
    // and without this gate that is an unbounded 401 loop (~46 req/s).
    if (Date.now() < retryAfterMs) return '';
    if (terminalAuthFailure()) return '';
    if (!inflight) {
        const jwt = fullToken();
        inflight = fetch('/api/auth/stream-token', {
            method: 'POST',
            headers: jwt ? { Authorization: `Bearer ${jwt}` } : {},
        })
            .then(r => {
                if (r.ok) return r.json();
                return r
                    .json()
                    .catch(() => null)
                    .then(body => {
                        handleAuthFailure(r.status, body);
                        return null;
                    });
            })
            // MUST sit before the classification below: a network-level reject
            // would otherwise skip it for the trailing catch, leaving the retry
            // gate open and the loop free to re-arm during an outage.
            .catch(() => null)
            .then(d => {
                const token = d?.data?.token || '';
                const ttl = (d?.data?.expires_in || 0) * 1000;
                // A successful (200) response resolves the auth state: a
                // non-empty token means auth is on; an empty token means auth
                // is not configured (the route is open). A failed response
                // (null) is an auth-on 401/expired-JWT case, so leave the state
                // unchanged rather than mislabelling it as "not configured".
                if (d) authConfigured = token !== '';
                if (!d) {
                    // Back off, and do NOT notify — a re-render is what re-arms
                    // the loop, and nothing changed for subscribers anyway.
                    // A handled 401 is terminal: no timer, it can't succeed.
                    if (!terminalAuthFailure()) {
                        retryAfterMs = Date.now() + retryDelayMs;
                        scheduleRetry(retryDelayMs);
                        retryDelayMs = Math.min(retryDelayMs * 2, RETRY_MAX_MS);
                    }
                    return '';
                }
                retryAfterMs = 0;
                retryDelayMs = RETRY_BASE_MS;
                rejectedJwt = null;
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
    retryAfterMs = 0;
    retryDelayMs = RETRY_BASE_MS;
    rejectedJwt = null;
    notify();
}
