import { useState, useCallback, useEffect, useRef } from 'react';
import { copyText } from '../../../utils/clipboard.js';

/** Copies the log locally — never upload it: logs carry ARR keys, Plex tokens, webhook URLs. */
export function useUploadState(logText) {
    const [copied, setCopied] = useState(false);
    const resetTimer = useRef(null);

    const handleUpload = useCallback(async () => {
        try {
            await copyText(logText || '');
            setCopied(true);
            if (resetTimer.current) {
                clearTimeout(resetTimer.current);
            }
            resetTimer.current = setTimeout(() => setCopied(false), 2000);
        } catch (error) {
            console.error('Failed to copy log to clipboard:', error);
        }
    }, [logText]);

    useEffect(() => () => clearTimeout(resetTimer.current), []);

    return {
        handleUpload,
        buttonIcon: copied ? 'check' : 'content_copy',
        tooltipText: copied ? 'Copied to clipboard' : 'Copy log to clipboard',
    };
}
