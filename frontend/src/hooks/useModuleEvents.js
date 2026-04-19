import { useEffect, useRef, useState, useCallback } from 'react';

const TOKEN_STORAGE_KEY = 'chub-auth-token';

/**
 * useModuleEvents - SSE-based hook for real-time module status updates
 *
 * Subscribes to the /api/modules/events SSE endpoint for push-based
 * status updates. Falls back to polling if SSE connection fails.
 *
 * NOTE: EventSource cannot send custom headers, so the auth token is
 * passed as a query parameter (?token=...) instead.
 *
 * @param {Object} options
 * @param {Function} [options.onStatusChange] - Callback when a module status changes
 * @param {boolean} [options.enabled=true] - Whether to connect
 * @returns {Object} { states, isConnected }
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

    // Keep callback ref current without re-triggering effect
    useEffect(() => {
        onStatusChangeRef.current = onStatusChange;
    }, [onStatusChange]);

    const connect = useCallback(() => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
        }

        // EventSource can't send Authorization headers — pass token via query param
        let sseUrl = '/api/modules/events';
        try {
            const token = localStorage.getItem(TOKEN_STORAGE_KEY);
            if (token) {
                sseUrl += `?token=${encodeURIComponent(token)}`;
            }
        } catch {
            // localStorage unavailable — connect without token
        }

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
        if (!enabled) {
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
                eventSourceRef.current = null;
            }
            // isConnected is already false via derivation; no setState needed.
            return;
        }

        connect();

        return () => {
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
                eventSourceRef.current = null;
            }
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
            }
        };
    }, [enabled, connect]);

    return { states, isConnected };
}

export default useModuleEvents;
