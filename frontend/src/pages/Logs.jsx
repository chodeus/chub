import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useLogModules } from '../hooks/useLogModules.js';
import { useLogFiles } from '../hooks/useLogFiles.js';
import { useLogContent } from '../hooks/useLogContent.js';
import { useLogPolling } from '../hooks/useLogPolling.js';
import { LogControls } from '../components/logs/controls/LogControls.jsx';
import { LogOutput } from '../components/logs/components/LogOutput.jsx';
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
    const [searchParams] = useSearchParams();
    // Seed selected module from ?module= so dashboard links deep-link into a
    // specific module's logs. After mount the local state wins — query
    // param is not re-read on subsequent param changes.
    const [selectedModule, setSelectedModule] = useState(() => searchParams.get('module') || '');
    const { logFiles, selectedLogFile, setSelectedLogFile } = useLogFiles(selectedModule);
    const { logText, refresh, inFlightRef } = useLogContent(selectedModule, selectedLogFile);
    useLogPolling(selectedModule, selectedLogFile, refresh, inFlightRef);

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
        'px-3 py-1 rounded-full font-mono text-[11px] font-semibold capitalize cursor-pointer border transition-colors select-none';
    const pillOff = 'bg-transparent text-fg-subtle border-border hover:text-fg';
    const levelOnClass = level => {
        if (level === 'critical') return 'bg-error/20 text-error border-error/40';
        if (level === 'error') return 'bg-error/15 text-error border-error/30';
        if (level === 'warning') return 'bg-warning/15 text-warning border-warning/30';
        if (level === 'info') return 'bg-primary/15 text-fg border-primary/30';
        // Debug — use accent so the "on" state is visually distinct from
        // pillOff (gray-on-gray previously made it impossible to tell the
        // toggle state).
        return 'bg-accent/15 text-accent border-accent/30';
    };

    return (
        <div className="flex flex-col gap-4 h-full">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        Logs
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        Tail module runs and diagnose failures.
                    </p>
                </div>
                <span className="inline-flex items-center gap-2 h-[30px] px-3 rounded-full bg-accent/10 border border-accent/25">
                    <span className="w-[7px] h-[7px] rounded-full bg-accent" aria-hidden="true" />
                    <span className="font-mono text-[11px] text-accent">live tail · 1s</span>
                </span>
            </div>

            <div
                className="flex flex-col flex-1 min-h-0 rounded-xl border border-border bg-surface overflow-hidden"
                style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
            >
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
                />

                {/* Filter pill bar */}
                <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-t border-border bg-surface-inset">
                    <span className="font-mono text-[10px] tracking-[1px] text-fg-faint mr-1">
                        LEVELS
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
                        className={`${pillBase} ${hideHeartbeat ? 'bg-primary/10 text-fg border-primary/30' : pillOff}`}
                        title="Hide repetitive progress / heartbeat lines (scheduler tick, rclone stats, merge progress)"
                    >
                        Hide heartbeat
                    </button>
                    <button
                        type="button"
                        onClick={() => setSortNewestFirst(prev => !prev)}
                        className={`${pillBase} ${sortNewestFirst ? 'bg-primary/10 text-fg border-primary/30' : pillOff}`}
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
