import { useState, useEffect, useCallback, useRef } from 'react';
import { logsAPI } from '../utils/api/logs.js';

const FROM_START = { offset: 0, id: '', start: 0 };

/** Log content plus a `refresh` for polling, which fetches only the lines added since the last read.
 *  In-flight fetches abort on unmount or selection change, and overlapping refreshes are skipped. */
export function useLogContent(selectedModule, selectedLogFile) {
    const [logText, setLogText] = useState('');
    // Bytes the server left out at the top of a log too big to view whole.
    const [skippedBytes, setSkippedBytes] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const posRef = useRef(FROM_START);

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
        setSkippedBytes(0);
        setLogText('');
        if (!currentKey) {
            setLoading(false);
        } else {
            setLoading(true);
        }
    }

    const applyRead = useCallback(read => {
        posRef.current = { offset: read.offset, id: read.id, start: read.start };
        setError(null);
        setSkippedBytes(read.start);
        if (read.reset) {
            setLogText(read.text);
        } else if (read.text) {
            setLogText(prev => prev + read.text);
        }
    }, []);

    useEffect(() => {
        if (!selectedModule || !selectedLogFile) return;

        const controller = new AbortController();
        abortRef.current = controller;
        inFlightRef.current = true;
        posRef.current = FROM_START;

        logsAPI
            .fetchLogContent(selectedModule, selectedLogFile, controller.signal, FROM_START)
            .then(read => {
                if (!controller.signal.aborted) applyRead(read);
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
            // refresh() replaces abortRef.current, so aborting the captured controller
            // would leave a live refresh to commit content for the old selection.
            abortRef.current?.abort();
            abortRef.current = null;
            inFlightRef.current = false;
        };
    }, [selectedModule, selectedLogFile, applyRead]);

    // Manual refresh function for polling. Skips if a fetch is already running
    // so slow log reads don't stack up when the poll interval fires repeatedly.
    const refresh = useCallback(async () => {
        if (!selectedModule || !selectedLogFile) return;
        if (inFlightRef.current) return;

        const controller = new AbortController();
        abortRef.current = controller;
        inFlightRef.current = true;

        try {
            const read = await logsAPI.fetchLogContent(
                selectedModule,
                selectedLogFile,
                controller.signal,
                posRef.current
            );
            if (!controller.signal.aborted) applyRead(read);
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
    }, [selectedModule, selectedLogFile, applyRead]);

    return {
        logText,
        skippedBytes,
        loading,
        error,
        refresh,
        inFlightRef,
    };
}
