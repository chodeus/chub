import { useState, useCallback, useRef } from 'react';
import { copyText } from '../../../utils/clipboard.js';

/**
 * useUploadState - Copy the current log text to the clipboard.
 *
 * This previously uploaded the raw displayed log to the public dpaste.com
 * pastebin (7-day public URL). CHUB logs can contain ARR API keys, Plex
 * tokens, and Discord webhook URLs, and the backend redaction is best-effort —
 * so a single click could publish credentials to a third party. Logs now stay
 * local: the action copies the displayed text to the clipboard, leaving the
 * user in control of where it goes (and free to redact before pasting). The
 * "Download log" button remains the way to get the full file.
 *
 * @param {string} logText - Current log text
 * @returns {Object} Upload (copy) state and actions
 */
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

    return {
        uploading: false,
        handleUpload,
        buttonIcon: copied ? 'check' : 'content_copy',
        tooltipText: copied ? 'Copied to clipboard' : 'Copy log to clipboard',
    };
}
