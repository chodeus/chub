import { useEffect, useRef } from 'react';

export const LOG_POLL_INTERVAL_MS = 5000;

/**
 * useLogPolling - Auto-refresh log content
 *
 * Polls the refresh callback every LOG_POLL_INTERVAL_MS when both module and file
 * are selected. Clears interval on unmount or when selections change.
 * Skips ticks while a fetch is already in flight so slow log reads don't
 * stack up.
 *
 * @param {string} selectedModule - Currently selected module
 * @param {string} selectedLogFile - Currently selected log file
 * @param {Function} refreshCallback - Function to call every interval
 * @param {{current: boolean}} [inFlightRef] - Optional ref to skip overlapping polls
 * @returns {void}
 */
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
