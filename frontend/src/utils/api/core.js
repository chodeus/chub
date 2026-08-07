const API_BASE = '/api';
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes
const REQUEST_TIMEOUT = 30000; // 30 seconds
const TOKEN_STORAGE_KEY = 'chub-auth-token';

class CacheEntry {
    constructor(data, ttl = CACHE_TTL) {
        this.data = data;
        this.timestamp = Date.now();
        this.ttl = ttl;
    }

    isValid() {
        return Date.now() - this.timestamp < this.ttl;
    }
}

/**
 * In-flight request tracker to prevent duplicate requests
 */
class RequestTracker {
    constructor() {
        this.requests = new Map();
    }

    /**
     * Get existing request promise or create new one
     * @param {string} key - Request identifier
     * @param {Function} requestFn - Function that returns a promise
     * @returns {Promise} Request promise
     */
    getOrCreate(key, requestFn) {
        if (this.requests.has(key)) {
            return this.requests.get(key);
        }

        const promise = requestFn().finally(() => {
            this.requests.delete(key);
        });

        this.requests.set(key, promise);
        return promise;
    }
}

/**
 * API Error class for consistent error handling
 */
class APIError extends Error {
    constructor(message, status, data = null, url = '') {
        super(message);
        this.name = 'APIError';
        this.status = status;
        this.data = data;
        this.url = url;
    }

    /**
     * Check if error is client-side (4xx)
     * @returns {boolean} True if client error
     */
    isClientError() {
        return this.status >= 400 && this.status < 500;
    }

    /**
     * Check if error is server-side (5xx)
     * @returns {boolean} True if server error
     */
    isServerError() {
        return this.status >= 500;
    }

    /**
     * Check if error should be retried
     * @returns {boolean} True if retry is appropriate
     */
    isRetryable() {
        return this.isServerError() || this.status === 429 || this.status === 408;
    }
}

// The backend normalises every 422 to the bare message "Validation error" and
// puts the per-field detail in `data`. Name the fields, or the user gets two
// words and no idea which input was wrong.
const MAX_NAMED_FIELDS = 3;

const fieldPath = loc =>
    (Array.isArray(loc) ? loc : [])
        // Drop the request-section prefix FastAPI prepends ("body", "query", …).
        .filter((part, i) => !(i === 0 && ['body', 'query', 'path', 'header'].includes(part)))
        .join('.');

/**
 * Human-readable message for an error payload, naming the offending fields on a
 * validation failure.
 * @param {Object} payload - Parsed error response body
 * @returns {string} Message, or '' when there is nothing better than the status
 */
export const describeError = payload => {
    const base = payload?.message || '';
    const details = payload?.data;
    if (payload?.error_code !== 'VALIDATION_ERROR' || !Array.isArray(details)) return base;

    const named = details
        .map(d => {
            // Explicit check, not `||`: a malformed entry must fall back to the
            // base message, not invent an "is invalid" with no field attached.
            if (!d || typeof d !== 'object' || typeof d.msg !== 'string' || d.msg === '') {
                return '';
            }
            const path = fieldPath(d.loc);
            return path ? `${path}: ${d.msg}` : d.msg;
        })
        .filter(Boolean);
    if (named.length === 0) return base;

    const shown = named.slice(0, MAX_NAMED_FIELDS).join('; ');
    const rest = named.length - MAX_NAMED_FIELDS;
    return `${base || 'Validation error'} — ${shown}${rest > 0 ? ` (+${rest} more)` : ''}`;
};

/**
 * Core API client with caching, error handling, and request management
 */
const apiCore = {
    cache: new Map(),
    requestTracker: new RequestTracker(),

    /**
     * Clear cache entries (all or by pattern)
     * @param {string|RegExp} pattern - Optional pattern to match cache keys
     */
    clearCache(pattern = null) {
        if (!pattern) {
            this.cache.clear();
            return;
        }

        const keys = Array.from(this.cache.keys());
        keys.forEach(key => {
            if (pattern instanceof RegExp ? pattern.test(key) : key.includes(pattern)) {
                this.cache.delete(key);
            }
        });
    },

    // Invalidate a mutated resource AND its parent list (e.g. /media/123 ->
    // /media, /media/collections/5 -> /media/collections) so lists/searches
    // don't keep showing a stale entry after a create/update/delete.
    clearCacheForMutation(url) {
        const path = url.split('?')[0];
        this.clearCache(path);
        const parent = path.replace(/\/[^/]+\/?$/, '');
        if (parent && parent !== path) this.clearCache(parent);
    },

    /**
     * Get cache key for request
     * @param {string} url - Request URL
     * @param {Object} options - Request options
     * @returns {string} Cache key
     */
    getCacheKey(url, options = {}) {
        // eslint-disable-next-line no-unused-vars
        const { body, ...cacheableOptions } = options;
        return `${url}:${JSON.stringify(cacheableOptions)}`;
    },

    /**
     * Check cache for valid entry
     * @param {string} cacheKey - Cache key to check
     * @returns {*} Cached data or null
     */
    getFromCache(cacheKey) {
        const entry = this.cache.get(cacheKey);
        if (entry && entry.isValid()) {
            return entry.data;
        }

        if (entry) {
            this.cache.delete(cacheKey);
        }

        return null;
    },

    /**
     * Store data in cache
     * @param {string} cacheKey - Cache key
     * @param {*} data - Data to cache
     * @param {number} ttl - Time to live in milliseconds
     */
    setCache(cacheKey, data, ttl = CACHE_TTL) {
        this.cache.set(cacheKey, new CacheEntry(data, ttl));
    },

    /**
     * Create AbortController with timeout
     * @param {number} timeout - Timeout in milliseconds
     * @returns {AbortController} Abort controller
     */
    createTimeoutController(timeout = REQUEST_TIMEOUT) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        // Clean up timeout on signal
        controller.signal.addEventListener('abort', () => {
            clearTimeout(timeoutId);
        });

        return controller;
    },

    /**
     * Combine the timeout signal with a caller's, so passing `signal` cancels a
     * request instead of being silently dropped — and the timeout still applies.
     * @param {AbortSignal} timeoutSignal - This request's timeout signal
     * @param {AbortSignal} [callerSignal] - Optional caller signal
     * @returns {AbortSignal} Signal aborting when either does
     */
    combineSignals(timeoutSignal, callerSignal) {
        if (!callerSignal) return timeoutSignal;
        if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.any === 'function') {
            return AbortSignal.any([timeoutSignal, callerSignal]);
        }
        // Relay for engines without AbortSignal.any.
        const relay = new AbortController();
        const sources = [callerSignal, timeoutSignal];
        const already = sources.find(s => s.aborted);
        if (already) {
            relay.abort(already.reason);
            return relay.signal;
        }
        // Detach from BOTH sources on the first abort. `once` only clears the
        // listener that fired; a caller signal often outlives the request, and a
        // stale listener there would pin this relay for the signal's lifetime.
        const handlers = new Map();
        const detach = () => sources.forEach(s => s.removeEventListener('abort', handlers.get(s)));
        sources.forEach(s => {
            const onAbort = () => {
                detach();
                relay.abort(s.reason);
            };
            handlers.set(s, onAbort);
            s.addEventListener('abort', onAbort);
        });
        return relay.signal;
    },

    /**
     * Make HTTP request with error handling
     * @param {string} url - Request URL
     * @param {Object} options - Fetch options
     * @returns {Promise<*>} Response data
     * @throws {APIError} API-specific error
     */
    async makeRequest(url, options = {}) {
        const controller = this.createTimeoutController(options.timeout);
        const fullUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;

        // Inject Bearer token if available
        const authHeaders = {};
        try {
            const token = localStorage.getItem(TOKEN_STORAGE_KEY);
            if (token) {
                authHeaders['Authorization'] = `Bearer ${token}`;
            }
        } catch {
            // localStorage unavailable — skip
        }

        // Destructure headers/signal out of options so the spread can't overwrite
        // the merged values set below.
        const {
            headers: optionHeaders,
            // eslint-disable-next-line no-unused-vars
            timeout: _timeout,
            signal: callerSignal,
            ...restOptions
        } = options;

        const isFormData = typeof FormData !== 'undefined' && restOptions.body instanceof FormData;
        const headers = {
            ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
            ...authHeaders,
            ...optionHeaders,
        };
        Object.keys(headers).forEach(key => {
            if (headers[key] === undefined || headers[key] === null) {
                delete headers[key];
            }
        });

        const requestOptions = {
            ...restOptions,
            headers,
            signal: this.combineSignals(controller.signal, callerSignal),
        };

        try {
            const response = await fetch(fullUrl, requestOptions);

            // Handle non-JSON responses
            const contentType = response.headers.get('content-type');
            let responseData;

            if (contentType && contentType.includes('application/json')) {
                responseData = await response.json();
            } else {
                responseData = { data: await response.text() };
            }

            // Handle 401 — clear stored token and redirect to login.
            // Only redirect for definitive auth failures (token invalid/expired),
            // not for transient issues. Check the error_code from the backend.
            if (response.status === 401) {
                const errorCode = responseData?.error_code;
                if (errorCode === 'AUTH_REQUIRED' || errorCode === 'AUTH_TOKEN_INVALID') {
                    try {
                        localStorage.removeItem(TOKEN_STORAGE_KEY);
                    } catch {
                        /* noop */
                    }
                    if (window.location.pathname !== '/login') {
                        window.location.href = '/login';
                    }
                }
                throw new APIError('Authentication required', 401, responseData, fullUrl);
            }

            // Handle HTTP errors
            if (!response.ok) {
                throw new APIError(
                    describeError(responseData) ||
                        `HTTP ${response.status}: ${response.statusText}`,
                    response.status,
                    responseData,
                    fullUrl
                );
            }

            // Handle CHUB error format
            if (responseData && responseData.success === false) {
                throw new APIError(
                    responseData.message || 'Request failed',
                    response.status,
                    responseData,
                    fullUrl
                );
            }

            return responseData;
        } catch (error) {
            if (error.name === 'AbortError') {
                // The caller cancelled deliberately — rethrow so it can recognise
                // its own abort instead of handling a phantom timeout.
                if (callerSignal?.aborted) throw error;
                throw new APIError('Request timeout', 408, null, fullUrl);
            }

            if (error instanceof APIError) {
                throw error;
            }

            // Network or other errors
            throw new APIError(`Network error: ${error.message}`, 0, null, fullUrl);
        } finally {
            // A completed request never aborts either signal, so the combined
            // signal would keep listening to a (often reused) caller signal until
            // the timeout eventually fired. Aborting here releases both listeners
            // and clears the pending timer.
            controller.abort();
        }
    },

    /**
     * GET request with caching
     * @param {string} url - Request URL
     * @param {Object} options - Request options
     * @param {boolean} options.useCache - Whether to use cache (default: true)
     * @param {number} options.cacheTTL - Cache TTL in milliseconds
     * @returns {Promise<*>} Response data
     */
    async get(url, options = {}) {
        const { useCache = true, cacheTTL, ...requestOptions } = options;
        const cacheKey = this.getCacheKey(url, requestOptions);

        // Check cache first
        if (useCache) {
            const cachedData = this.getFromCache(cacheKey);
            if (cachedData !== null) {
                return cachedData;
            }
        }

        const run = async () => {
            const data = await this.makeRequest(url, {
                method: 'GET',
                ...requestOptions,
            });

            // Cache successful responses
            if (useCache && data) {
                this.setCache(cacheKey, data, cacheTTL);
            }

            return data;
        };

        // A caller signal must NOT reach a promise shared with other callers: an
        // AbortSignal stringifies to {} so every caller collapses onto the same
        // tracker key, and one abort would reject everyone else's request. Give
        // a cancelling caller its own request instead.
        if (requestOptions.signal) {
            return run();
        }

        // Use request tracker to prevent duplicate requests
        return this.requestTracker.getOrCreate(cacheKey, run);
    },

    /**
     * POST request with cache invalidation
     * @param {string} url - Request URL
     * @param {*} data - Request body data
     * @param {Object} options - Request options
     * @returns {Promise<*>} Response data
     */
    async post(url, data, options = {}) {
        const isFormData = typeof FormData !== 'undefined' && data instanceof FormData;
        const response = await this.makeRequest(url, {
            method: 'POST',
            body: isFormData ? data : JSON.stringify(data),
            ...options,
        });

        // Clear the resource + its parent list cache.
        this.clearCacheForMutation(url);

        return response;
    },

    /**
     * PUT request with cache invalidation
     * @param {string} url - Request URL
     * @param {*} data - Request body data
     * @param {Object} options - Request options
     * @returns {Promise<*>} Response data
     */
    async put(url, data, options = {}) {
        const isFormData = typeof FormData !== 'undefined' && data instanceof FormData;
        const response = await this.makeRequest(url, {
            method: 'PUT',
            body: isFormData ? data : JSON.stringify(data),
            ...options,
        });

        // Clear the resource + its parent list cache.
        this.clearCacheForMutation(url);

        return response;
    },

    /**
     * DELETE request with cache invalidation
     * @param {string} url - Request URL
     * @param {Object} options - Request options
     * @returns {Promise<*>} Response data
     */
    async delete(url, options = {}) {
        const response = await this.makeRequest(url, {
            method: 'DELETE',
            ...options,
        });

        // Clear the resource + its parent list cache.
        this.clearCacheForMutation(url);

        return response;
    },

    /**
     * PATCH request with cache invalidation
     * @param {string} url - Request URL
     * @param {*} data - Request body data
     * @param {Object} options - Request options
     * @returns {Promise<*>} Response data
     */
    async patch(url, data, options = {}) {
        const response = await this.makeRequest(url, {
            method: 'PATCH',
            body: JSON.stringify(data),
            ...options,
        });

        // Clear the resource + its parent list cache.
        this.clearCacheForMutation(url);

        return response;
    },
};

export { apiCore, APIError };
