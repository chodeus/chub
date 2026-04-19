import { useState, useEffect, useCallback, useRef } from 'react';
import { logsAPI } from '../utils/api/logs.js';

/**
 * useLogContent - Fetch log file content
 *
 * Fetches log content when module and file are selected, and provides
 * a manual refresh function for polling. In-flight fetches are cancelled
 * on unmount or when the selected module/file changes, and overlapping
 * refresh calls are skipped so slow fetches don't pile up.
 *
 * @param {string} selectedModule - Currently selected module
 * @param {string} selectedLogFile - Currently selected log file
 * @returns {Object} Log content state
 * @property {string} logText - Log file content
 * @property {boolean} loading - Loading state
 * @property {Error|null} error - Error state
 * @property {Function} refresh - Manual refresh function (returns Promise)
 * @property {{current: boolean}} inFlightRef - Ref that's true while a fetch is running
 */
export function useLogContent(selectedModule, selectedLogFile) {
    const [logText, setLogText] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // Tracks whether a fetch is currently in flight. The polling hook reads
    // this to skip ticks that would overlap with an ongoing request.
    const inFlightRef = useRef(false);
    const abortRef = useRef(null);

    // Reset loading/error state at render time when the key changes. This is
    // the "adjusting state when a prop changes" pattern from the React docs —
    // conditional setState during render, not a setState-in-effect.
    const currentKey =
        selectedModule && selectedLogFile ? `${selectedModule}|${selectedLogFile}` : '';
    const [lastKey, setLastKey] = useState(currentKey);
    if (lastKey !== currentKey) {
        setLastKey(currentKey);
        setError(null);
        if (!currentKey) {
            setLogText('');
            setLoading(false);
        } else {
            setLoading(true);
        }
    }

    useEffect(() => {
        if (!selectedModule || !selectedLogFile) return;

        const controller = new AbortController();
        abortRef.current = controller;
        inFlightRef.current = true;

        logsAPI
            .fetchLogContent(selectedModule, selectedLogFile, controller.signal)
            .then(content => {
                if (!controller.signal.aborted) setLogText(content);
            })
            .catch(err => {
                if (err?.name === 'AbortError') return;
                console.error('Failed to load log content:', err);
                setError(err);
                setLogText('');
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
                if (abortRef.current === controller) {
                    abortRef.current = null;
                    inFlightRef.current = false;
                }
            });

        return () => {
            controller.abort();
            if (abortRef.current === controller) {
                abortRef.current = null;
                inFlightRef.current = false;
            }
        };
    }, [selectedModule, selectedLogFile]);

    // Manual refresh function for polling. Skips if a fetch is already running
    // so slow log reads don't stack up when the poll interval fires repeatedly.
    const refresh = useCallback(async () => {
        if (!selectedModule || !selectedLogFile) return;
        if (inFlightRef.current) return;

        const controller = new AbortController();
        abortRef.current = controller;
        inFlightRef.current = true;

        try {
            const content = await logsAPI.fetchLogContent(
                selectedModule,
                selectedLogFile,
                controller.signal
            );
            if (!controller.signal.aborted) setLogText(content);
        } catch (err) {
            if (err?.name === 'AbortError') return;
            // Silent failure during polling - don't show toast spam
            console.error('Failed to refresh log content:', err);
        } finally {
            if (abortRef.current === controller) {
                abortRef.current = null;
                inFlightRef.current = false;
            }
        }
    }, [selectedModule, selectedLogFile]);

    return {
        logText,
        loading,
        error,
        refresh,
        inFlightRef,
    };
}
