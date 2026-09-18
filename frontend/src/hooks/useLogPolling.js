import { useEffect, useRef } from 'react';

export const LOG_POLL_INTERVAL_MS = 5000;

/** Polls refreshCallback every LOG_POLL_INTERVAL_MS while a module and file are selected, skipping ticks that overlap an in-flight fetch. */
export function useLogPolling(selectedModule, selectedLogFile, refreshCallback, inFlightRef) {
    const intervalRef = useRef(null);

    useEffect(() => {
        // Only poll when both module and file selected
        if (!selectedModule || !selectedLogFile || !refreshCallback) {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
            }
            return;
        }

        // Clear existing interval
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
        }

        intervalRef.current = setInterval(() => {
            if (inFlightRef?.current) return;
            refreshCallback();
        }, LOG_POLL_INTERVAL_MS);

        // Cleanup on unmount or when dependencies change
        return () => {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
            }
        };
    }, [selectedModule, selectedLogFile, refreshCallback, inFlightRef]);
}
