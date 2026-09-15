import React from 'react';
import { useLogControls } from '../context/LogControlsContext';

/**
 * LogFileSelect — compact dark-inset log-file picker with a mono filename,
 * matching the redesign mock. Disabled when no files are available.
 */
export const LogFileSelect = () => {
    const { logFiles, selectedLogFile, onLogFileChange } = useLogControls();
    const disabled = !logFiles || logFiles.length === 0;

    return (
        <div
            className={`flex items-center w-full h-11 px-3 rounded-lg bg-surface-inset border border-border focus-within:border-primary transition-colors ${
                disabled ? 'opacity-50' : ''
            }`}
        >
            <select
                value={selectedLogFile || ''}
                disabled={disabled}
                onChange={e => onLogFileChange(e.target.value)}
                aria-label="Select log file"
                className="flex-1 min-w-0 h-full bg-transparent border-0 outline-none font-mono text-xs text-fg-muted cursor-pointer disabled:cursor-not-allowed"
            >
                <option value="">Select log file</option>
                {logFiles &&
                    logFiles.map(file => (
                        <option key={file} value={file}>
                            {file}
                        </option>
                    ))}
            </select>
        </div>
    );
};
