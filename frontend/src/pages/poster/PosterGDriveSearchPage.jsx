import React, { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { LoadingButton, SegmentedControl, StatusDot } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';
import { formatDate } from '../../utils/datetime.js';

const SORT_OPTIONS = [
    { value: 'name', label: 'Name' },
    { value: 'last_synced', label: 'Last synced' },
    { value: 'size', label: 'Size' },
];

const FILTER_OPTIONS = [
    { value: 'all', label: 'All' },
    { value: 'stale', label: 'Stale (>7 days)' },
    { value: 'never', label: 'Never synced' },
];

const STALE_DAYS = 7;
const STALE_MS = STALE_DAYS * 24 * 60 * 60 * 1000;

// `last_updated` arrives as either YYYYMMDD or an ISO-ish string.
// Returns ms-since-epoch, or null if missing/unparseable.
const parseLastSynced = value => {
    if (!value) return null;
    if (typeof value === 'string' && value.length === 8 && /^\d{8}$/.test(value)) {
        const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
        const ms = Date.parse(iso);
        return Number.isNaN(ms) ? null : ms;
    }
    const ms = Date.parse(value);
    return Number.isNaN(ms) ? null : ms;
};

const formatSize = bytes => {
    if (!bytes || bytes <= 0) return null;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
};

const formatLastSynced = ms => (ms == null ? 'Never synced' : formatDate(ms));

const PosterGDriveSearchPage = () => {
    const toast = useToast();
    const [syncingFolders, setSyncingFolders] = useState(new Set());
    const [sortBy, setSortBy] = useState('name');
    const [filterBy, setFilterBy] = useState('all');
    // Frozen at mount so the staleness threshold is stable across re-renders.
    const [now] = useState(() => Date.now());

    const { data, isLoading, refresh } = useApiData({
        apiFunction: () => postersAPI.searchGoogleDrive({}),
        options: { showErrorToast: false },
    });

    const sources = useMemo(() => data?.data?.sources || [], [data]);

    const { execute: syncAll, isLoading: isSyncingAll } = useApiMutation(
        () => postersAPI.syncGDriveFolders(sources.map(s => s.name)),
        {
            successMessage: 'All folders synced',
            onSuccess: () => refresh(),
        }
    );

    const syncOne = async folderName => {
        if (!folderName) return;
        setSyncingFolders(prev => new Set([...prev, folderName]));
        try {
            await postersAPI.syncGDriveFolders([folderName]);
            toast.success(`Synced "${folderName}"`);
            refresh();
        } catch {
            toast.error(`Failed to sync "${folderName}"`);
        } finally {
            setSyncingFolders(prev => {
                const next = new Set(prev);
                next.delete(folderName);
                return next;
            });
        }
    };

    const displayedSources = useMemo(() => {
        const enriched = sources.map(s => ({
            ...s,
            _lastSyncedMs: parseLastSynced(s.last_updated),
        }));

        const filtered = enriched.filter(s => {
            if (filterBy === 'never') return s._lastSyncedMs == null;
            if (filterBy === 'stale') {
                return s._lastSyncedMs == null || now - s._lastSyncedMs > STALE_MS;
            }
            return true;
        });

        const sorted = [...filtered].sort((a, b) => {
            if (sortBy === 'size') return (b.size_bytes || 0) - (a.size_bytes || 0);
            if (sortBy === 'last_synced') {
                // Most-recent first; "never synced" sinks to the bottom.
                const av = a._lastSyncedMs ?? -Infinity;
                const bv = b._lastSyncedMs ?? -Infinity;
                return bv - av;
            }
            return (a.name || '').localeCompare(b.name || '');
        });

        return sorted;
    }, [sources, filterBy, sortBy, now]);

    const totalFiles = useMemo(
        () => sources.reduce((sum, s) => sum + (s.file_count || 0), 0),
        [sources]
    );
    const lastSyncLabel = useMemo(() => {
        const ms = sources
            .map(s => parseLastSynced(s.last_updated))
            .filter(v => v != null)
            .reduce((max, v) => Math.max(max, v), 0);
        return ms ? formatDate(ms) : '—';
    }, [sources]);

    return (
        <div className="flex flex-col gap-5">
            {/* Toolbar */}
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        GDrive Sources
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        Google Drive folders{' '}
                        <span className="font-mono text-fg-muted">sync_gdrive</span> pulls posters
                        from via rclone.
                    </p>
                </div>
                <div className="flex items-center gap-2.5">
                    {sources.length > 0 && (
                        <LoadingButton
                            loading={isSyncingAll}
                            loadingText="Syncing…"
                            variant="surface"
                            icon="sync"
                            onClick={() => syncAll()}
                        >
                            Sync all
                        </LoadingButton>
                    )}
                    <Link
                        to="/settings/modules"
                        className="inline-flex items-center gap-1.5 h-[38px] px-4 rounded-lg bg-primary text-on-color font-display text-[13.5px] font-semibold no-underline hover:brightness-110 transition"
                        style={{ boxShadow: '0 4px 16px -5px var(--primary)' }}
                    >
                        <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                            add
                        </span>
                        Add source
                    </Link>
                </div>
            </div>

            {/* Summary banner */}
            {sources.length > 0 && (
                <div className="flex items-center gap-3 px-4 py-3 rounded-[10px] bg-success/[0.08] border border-success/25">
                    <span className="w-[30px] h-[30px] rounded-lg bg-success/15 flex items-center justify-center shrink-0">
                        <span className="material-symbols-outlined text-success text-[18px]">
                            cloud_done
                        </span>
                    </span>
                    <div className="min-w-0">
                        <div className="text-[13.5px] font-semibold text-fg">
                            Google Drive sources
                        </div>
                        <div className="font-mono text-[11px] text-fg-subtle mt-0.5">
                            {sources.length} sources · {totalFiles.toLocaleString()} posters cached
                            · last sync {lastSyncLabel}
                        </div>
                    </div>
                </div>
            )}

            {/* Controls */}
            {sources.length > 0 && (
                <div className="flex flex-wrap items-center gap-3">
                    <SegmentedControl
                        size="sm"
                        options={FILTER_OPTIONS}
                        value={filterBy}
                        onChange={setFilterBy}
                    />
                    <div className="flex items-center h-9 rounded-[9px] bg-surface border border-border">
                        <span className="material-symbols-outlined text-[16px] text-fg-subtle pl-3">
                            sort
                        </span>
                        <select
                            value={sortBy}
                            onChange={e => setSortBy(e.target.value)}
                            className="h-full bg-transparent border-0 outline-none text-[13px] text-fg-muted pl-1.5 pr-3 cursor-pointer"
                            aria-label="Sort sources"
                        >
                            {SORT_OPTIONS.map(o => (
                                <option key={o.value} value={o.value}>
                                    Sort: {o.label}
                                </option>
                            ))}
                        </select>
                    </div>
                </div>
            )}

            {isLoading && <Spinner size="large" text="Loading GDrive sources..." center />}

            {!isLoading && sources.length === 0 && (
                <div className="text-center py-16 text-fg-subtle">
                    <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                        cloud_off
                    </span>
                    <p className="text-lg">No GDrive sources configured</p>
                    <p className="text-sm mt-2">
                        Add a Google Drive folder in module settings to see it here.
                    </p>
                </div>
            )}

            {!isLoading && sources.length > 0 && displayedSources.length === 0 && (
                <div className="text-center py-16 text-fg-subtle">
                    <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                        filter_alt_off
                    </span>
                    <p className="text-lg">No folders match the current filter</p>
                </div>
            )}

            {/* Sources table */}
            {!isLoading && displayedSources.length > 0 && (
                <section
                    className="bg-surface border border-border rounded-xl overflow-hidden"
                    style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
                >
                    <div className="overflow-x-auto">
                        <div className="min-w-[720px]">
                            <div className="grid grid-cols-[1.4fr_1.4fr_0.8fr_1fr_0.9fr_80px] gap-3.5 px-[18px] py-2.5 border-b border-border font-mono text-[10px] tracking-[1px] text-fg-faint">
                                <span>SOURCE</span>
                                <span>DRIVE FOLDER</span>
                                <span>POSTERS</span>
                                <span>LAST SYNC</span>
                                <span>STATUS</span>
                                <span className="text-right">ACTION</span>
                            </div>
                            {displayedSources.map((source, i) => {
                                const syncing = syncingFolders.has(source.name) || isSyncingAll;
                                const st = syncing
                                    ? { label: 'Syncing', dot: 'running', tone: 'text-accent' }
                                    : source._lastSyncedMs
                                      ? { label: 'Synced', dot: 'success', tone: 'text-success' }
                                      : { label: 'Never', dot: 'idle', tone: 'text-fg-faint' };
                                return (
                                    <div
                                        key={source.id || source.name || i}
                                        className="grid grid-cols-[1.4fr_1.4fr_0.8fr_1fr_0.9fr_80px] gap-3.5 items-center px-[18px] py-3 border-b border-border-light hover:bg-row-hover transition-colors"
                                    >
                                        <div className="flex items-center gap-2.5 min-w-0">
                                            <span className="w-[30px] h-[30px] rounded-lg bg-accent/12 flex items-center justify-center shrink-0">
                                                <span className="material-symbols-outlined text-accent text-[16px]">
                                                    folder
                                                </span>
                                            </span>
                                            <span className="font-semibold text-sm text-fg truncate">
                                                {source.name}
                                            </span>
                                        </div>
                                        <span
                                            className="font-mono text-[11.5px] text-fg-data truncate"
                                            title={source.location}
                                        >
                                            {source.location}
                                        </span>
                                        <span className="font-mono text-xs text-fg-muted">
                                            {(source.file_count || 0).toLocaleString()}
                                        </span>
                                        <span
                                            className="font-mono text-[11.5px] text-fg-subtle truncate"
                                            title={
                                                source.size_bytes > 0
                                                    ? formatSize(source.size_bytes)
                                                    : undefined
                                            }
                                        >
                                            {formatLastSynced(source._lastSyncedMs)}
                                        </span>
                                        <span
                                            className={`flex items-center gap-1.5 text-xs font-semibold ${st.tone}`}
                                        >
                                            <StatusDot status={st.dot} size={6} ring={false} />
                                            {st.label}
                                        </span>
                                        <div className="flex justify-end">
                                            <LoadingButton
                                                loading={syncingFolders.has(source.name)}
                                                loadingText=""
                                                variant="ghost"
                                                size="small"
                                                icon="sync"
                                                aria-label={`Sync ${source.name}`}
                                                onClick={() => syncOne(source.name)}
                                            />
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </section>
            )}
        </div>
    );
};

export default PosterGDriveSearchPage;
