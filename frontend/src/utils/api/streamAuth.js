/**
 * Short-lived, scope-limited "stream" tokens for URL-embedded auth.
 *
 * `<img>` and `EventSource` can't send an Authorization header, so those URLs
 * carry the token as a query param — which leaks into proxy/access logs and
 * browser history. Putting the full 24h session token there is dangerous; this
 * mints a minutes-long, GET-only, image/SSE-scoped token instead (see
 * POST /api/auth/stream-token + AuthMiddleware STREAM_PATH_PREFIXES).
 */

const TOKEN_STORAGE_KEY = 'chub-auth-token';
const SKEW_MS = 30_000; // refresh this long before expiry

let cached = null; // { token: string, expMs: number }
let inflight = null;

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

/** Fetch (or reuse) a valid stream token. Concurrent callers share one request. */
export async function ensureStreamToken() {
    const current = fresh();
    if (current) return current;
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
                cached = token ? { token, expMs: Date.now() + ttl } : null;
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
 * auth (see AuthContext) so it's ready before image grids render.
 */
export function streamTokenParam() {
    const current = fresh();
    if (!current) ensureStreamToken();
    return current;
}

export function clearStreamToken() {
    cached = null;
    inflight = null;
}
