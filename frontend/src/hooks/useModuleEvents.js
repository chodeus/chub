import { useEffect, useRef, useState, useCallback } from 'react';

import { ensureStreamToken } from '../utils/api/streamAuth.js';

/**
 * Subscribes to /api/modules/events (SSE) and reconnects 5s after a connection error.
 * EventSource cannot send headers, so the short-lived stream token goes in the query.
 */
export function useModuleEvents({ onStatusChange, enabled = true } = {}) {
    const [states, setStates] = useState({});
    // Internal "socket is live" flag. Exposed `isConnected` is derived
    // (false whenever disabled) so we never need to setState-in-effect on disable.
    const [hasOpenSocket, setHasOpenSocket] = useState(false);
    const isConnected = enabled && hasOpenSocket;

    const eventSourceRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const onStatusChangeRef = useRef(onStatusChange);
    const connectRef = useRef(null);
    // Bumped on every teardown/disable: a connect() resuming after the token await
    // must not create an EventSource that cleanup has already run past.
    const generationRef = useRef(0);

    // Keep callback ref current without re-triggering effect
    useEffect(() => {
        onStatusChangeRef.current = onStatusChange;
    }, [onStatusChange]);

    const connect = useCallback(async () => {
        const generation = generationRef.current;
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
        }

        // EventSource can't send Authorization headers — pass a short-lived,
        // scope-limited stream token via query param, not the session JWT.
        let sseUrl = '/api/modules/events';
        try {
            const token = await ensureStreamToken();
            if (token) {
                sseUrl += `?token=${encodeURIComponent(token)}`;
            }
        } catch {
            // token unavailable — connect without (middleware will 401)
        }

        if (generation !== generationRef.current) return;

        const es = new EventSource(sseUrl);
        eventSourceRef.current = es;

        es.onopen = () => {
            setHasOpenSocket(true);
            // Clear any pending reconnect
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
        };

        es.onmessage = event => {
            try {
                const data = JSON.parse(event.data);
                if (data.event === 'status_change' && data.module) {
                    setStates(prev => ({
                        ...prev,
                        [data.module]: data,
                    }));
                    if (onStatusChangeRef.current) {
                        onStatusChangeRef.current(data);
                    }
                }
            } catch {
                // Ignore parse errors (keepalive comments, etc.)
            }
        };

        es.onerror = () => {
            setHasOpenSocket(false);
            es.close();
            eventSourceRef.current = null;

            // Reconnect after 5 seconds via ref — avoids use-before-define.
            reconnectTimeoutRef.current = setTimeout(() => {
                if (enabled && connectRef.current) connectRef.current();
            }, 5000);
        };
    }, [enabled]);

    // Mirror connect into a ref so the reconnect timer can call it without
    // forward-referencing the binding.
    useEffect(() => {
        connectRef.current = connect;
    }, [connect]);

    useEffect(() => {
        // One teardown for both paths: disabling left the reconnect timer armed,
        // so it fired and reconnected a hook that was meant to be off.
        const teardown = () => {
            generationRef.current += 1;
            // `enabled && hasOpenSocket` masks a stale true while disabled, so without
            // this re-enabling reports isConnected before the new stream opens.
            setHasOpenSocket(false);
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
                eventSourceRef.current = null;
            }
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
        };

        if (!enabled) {
            teardown();
            // isConnected is already false via derivation; no setState needed.
            return;
        }

        connect();

        return teardown;
    }, [enabled, connect]);

    return { states, isConnected };
}

export default useModuleEvents;
