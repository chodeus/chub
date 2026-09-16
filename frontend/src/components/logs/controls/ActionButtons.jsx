import React from 'react';
import { useLogControls } from '../context/LogControlsContext';
import { useUploadState } from '../hooks/useUploadState';

/** Download the log file, or copy the displayed text to the clipboard. */
export const ActionButtons = ({ logText }) => {
    const { onDownload } = useLogControls();
    const uploadState = useUploadState(logText);

    return (
        <div className="flex items-center gap-2">
            {/* Download button */}
            <button
                type="button"
                onClick={onDownload}
                className="flex items-center justify-center p-2 rounded-lg border border-border bg-input text-fg hover:bg-surface-alt transition-colors min-h-11 min-w-11"
                title="Download log"
                aria-label="Download log"
            >
                <span className="material-symbols-outlined text-xl">download</span>
            </button>

            <button
                type="button"
                onClick={uploadState.handleUpload}
                className="flex items-center justify-center p-2 rounded-lg border border-border bg-input text-fg hover:bg-surface-alt transition-colors min-h-11 min-w-11"
                title={uploadState.tooltipText}
                aria-label={uploadState.tooltipText}
            >
                <span className="material-symbols-outlined text-xl">{uploadState.buttonIcon}</span>
            </button>
        </div>
    );
};
