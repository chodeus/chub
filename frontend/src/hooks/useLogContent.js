import { useState, useEffect, useCallback } from 'react';
import { logsAPI } from '../utils/api/logs.js';

/**
 * useLogContent - Fetch log file content
 *
 * Fetches log content when module and file are selected, and provides
 * a manual refresh function for polling.
 *
 * @param {string} selectedModule - Currently selected module
 * @param {string} selectedLogFile - Currently selected log file
 * @returns {Object} Log content state
 * @property {string} logText - Log file content
 * @property {boolean} loading - Loading state
 * @property {Error|null} error - Error state
 * @property {Function} refresh - Manual refresh function
 */
export function useLogContent(selectedModule, selectedLogFile) {
    const [logText, setLogText] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // Reset loading/error state at render time when the key changes. This is
    // the "adjusting state when a prop changes" pattern from the React docs —
    // conditional setState during render, not a setState-in-effect.
    const currentKey = selectedModule && selectedLogFile ? `${selectedModule}|${selectedLogFile}` : '';
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
        let cancelled = false;

        logsAPI
            .fetchLogContent(selectedModule, selectedLogFile)
            .then(content => {
                if (!cancelled) setLogText(content);
            })
            .catch(err => {
                if (cancelled) return;
                console.error('Failed to load log content:', err);
                setError(err);
                setLogText('');
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [selectedModule, selectedLogFile]);

    // Manual refresh function for polling
    const refresh = useCallback(async () => {
        if (!selectedModule || !selectedLogFile) return;

        try {
            const content = await logsAPI.fetchLogContent(selectedModule, selectedLogFile);
            setLogText(content);
        } catch (err) {
            // Silent failure during polling - don't show toast spam
            console.error('Failed to refresh log content:', err);
        }
    }, [selectedModule, selectedLogFile]);

    return {
        logText,
        loading,
        error,
        refresh,
    };
}
