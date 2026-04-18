import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useLogModules } from '../hooks/useLogModules.js';
import { useLogFiles } from '../hooks/useLogFiles.js';
import { useLogContent } from '../hooks/useLogContent.js';
import { useLogPolling } from '../hooks/useLogPolling.js';
import { LogControls } from '../components/logs/controls/LogControls.jsx';
import { LogOutput } from '../components/logs/components/LogOutput.jsx';
import { PageHeader } from '../components/ui';
import { logsAPI } from '../utils/api/logs.js';

const LOG_LEVELS = ['critical', 'error', 'warning', 'info', 'debug'];

/**
 * Logs Page - Log viewer with real-time updates
 *
 * Provides comprehensive log viewing interface with:
 * - Module and file selection
 * - Real-time content updates (1s polling)
 * - Search and highlighting
 * - Log-level filtering
 * - Sort order (newest/oldest first)
 * - Scroll-to-top/bottom navigation
 * - Download and upload capabilities
 * - Keyboard shortcuts (Ctrl/Cmd+F for search)
 */
export default function Logs() {
    // Data hooks
    const { modules } = useLogModules();
    const [selectedModule, setSelectedModule] = useState('');
    const { logFiles, selectedLogFile, setSelectedLogFile } = useLogFiles(selectedModule);
    const { logText, refresh } = useLogContent(selectedModule, selectedLogFile);
    useLogPolling(selectedModule, selectedLogFile, refresh);

    // Search state
    const [searchTerm, setSearchTerm] = useState('');
    const [activeLevels, setActiveLevels] = useState(new Set(LOG_LEVELS));
    const [hideHeartbeat, setHideHeartbeat] = useState(true);
    const [sortNewestFirst, setSortNewestFirst] = useState(false);

    // Ref for log output container scrolling
    const logOutputRef = useRef(null);

    const toggleLevel = level => {
        setActiveLevels(prev => {
            const next = new Set(prev);
            if (next.has(level)) next.delete(level);
            else next.add(level);
            return next;
        });
    };

    const scrollToTop = useCallback(() => {
        const el = logOutputRef.current?.querySelector('.flex-1.overflow-y-auto');
        if (el) el.scrollTop = 0;
    }, []);

    const scrollToBottom = useCallback(() => {
        const el = logOutputRef.current?.querySelector('.flex-1.overflow-y-auto');
        if (el) el.scrollTop = el.scrollHeight;
    }, []);

    // Refs for keyboard shortcuts
    const searchInputRef = useRef(null);

    // Download handler
    const handleDownload = async () => {
        if (!selectedModule || !selectedLogFile) {
            console.warn('Select a module and log file first');
            return;
        }

        try {
            await logsAPI.downloadLogFile(selectedModule, selectedLogFile);
        } catch (error) {
            console.error('Failed to download log file:', error);
        }
    };

    // Upload handler (delegated to ActionButtons via useUploadState)
    const handleUpload = async () => {
        if (!selectedModule || !selectedLogFile) {
            throw new Error('Select a module and log file first');
        }
        if (!logText || !logText.trim()) {
            throw new Error('No log content to upload');
        }

        return await logsAPI.uploadLogToPaste(logText);
    };

    // Keyboard shortcuts (Ctrl/Cmd+F)
    useEffect(() => {
        function handleKeyDown(e) {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
                e.preventDefault();
                if (searchInputRef.current) {
                    searchInputRef.current.focus();
                    searchInputRef.current.select();
                }
            }
        }

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

    const pillBase =
        'px-3 py-1.5 rounded-full text-xs font-medium capitalize cursor-pointer border transition-colors select-none';
    const pillOff = 'bg-transparent text-tertiary border-border hover:text-primary';
    const levelOnClass = level => {
        if (level === 'critical') return 'bg-error/20 text-error border-error/40';
        if (level === 'error') return 'bg-error/15 text-error border-error/30';
        if (level === 'warning') return 'bg-warning/15 text-warning border-warning/30';
        if (level === 'info') return 'bg-primary/15 text-primary border-primary/30';
        return 'bg-surface-alt text-secondary border-border';
    };

    return (
        <div className="flex flex-col gap-4 h-full">
            <PageHeader
                title="Logs"
                description="Tail module runs and diagnose failures."
                badge={2}
                icon="description"
            />

            <div className="flex flex-col rounded-lg border border-border-light bg-surface overflow-hidden">
                <LogControls
                    modules={modules}
                    logFiles={logFiles}
                    selectedModule={selectedModule}
                    selectedLogFile={selectedLogFile}
                    searchTerm={searchTerm}
                    logText={logText}
                    searchInputRef={searchInputRef}
                    onModuleChange={setSelectedModule}
                    onLogFileChange={setSelectedLogFile}
                    onSearchChange={setSearchTerm}
                    onDownload={handleDownload}
                    onUpload={handleUpload}
                />

                {/* Filter pill bar */}
                <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-t border-border-light bg-surface-alt">
                    <span className="text-xs uppercase tracking-wider text-tertiary font-semibold mr-1">
                        Levels
                    </span>
                    {LOG_LEVELS.map(level => (
                        <button
                            key={level}
                            type="button"
                            onClick={() => toggleLevel(level)}
                            className={`${pillBase} ${activeLevels.has(level) ? levelOnClass(level) : pillOff}`}
                        >
                            {level}
                        </button>
                    ))}
                    <span className="mx-2 h-5 w-px bg-border-light" aria-hidden="true" />
                    <button
                        type="button"
                        onClick={() => setHideHeartbeat(prev => !prev)}
                        className={`${pillBase} ${hideHeartbeat ? 'bg-primary/10 text-primary border-primary/30' : pillOff}`}
                        title="Hide 'Scheduler is alive' heartbeat messages"
                    >
                        Hide heartbeat
                    </button>
                    <button
                        type="button"
                        onClick={() => setSortNewestFirst(prev => !prev)}
                        className={`${pillBase} ${sortNewestFirst ? 'bg-primary/10 text-primary border-primary/30' : pillOff}`}
                        title={sortNewestFirst ? 'Showing newest first' : 'Showing oldest first'}
                    >
                        {sortNewestFirst ? 'Newest first' : 'Oldest first'}
                    </button>
                    <span className="mx-2 h-5 w-px bg-border-light" aria-hidden="true" />
                    <button
                        type="button"
                        onClick={scrollToTop}
                        className={`${pillBase} ${pillOff} inline-flex items-center gap-1`}
                        title="Scroll to top"
                    >
                        <span className="material-symbols-outlined text-sm">
                            vertical_align_top
                        </span>
                        Top
                    </button>
                    <button
                        type="button"
                        onClick={scrollToBottom}
                        className={`${pillBase} ${pillOff} inline-flex items-center gap-1`}
                        title="Scroll to bottom"
                    >
                        <span className="material-symbols-outlined text-sm">
                            vertical_align_bottom
                        </span>
                        Bottom
                    </button>
                </div>

                <div ref={logOutputRef} className="flex flex-col flex-1 min-h-0">
                    <LogOutput
                        logText={logText}
                        searchTerm={searchTerm}
                        activeLevels={activeLevels}
                        hideHeartbeat={hideHeartbeat}
                        sortNewestFirst={sortNewestFirst}
                    />
                </div>
            </div>
        </div>
    );
}
