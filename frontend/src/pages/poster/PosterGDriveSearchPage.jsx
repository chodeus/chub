import React, { useState, useMemo } from 'react';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { Button, LoadingButton, PageHeader } from '../../components/ui/index.js';
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
    const [pickerSelection, setPickerSelection] = useState('');
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

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="GDrive Sources"
                description="Browse your configured Google Drive folders and trigger a sync to pull their contents into your local asset cache."
                badge={1}
                icon="cloud"
                actions={
                    sources.length > 0 ? (
                        <LoadingButton
                            loading={isSyncingAll}
                            loadingText="Syncing All..."
                            variant="primary"
                            icon="sync"
                            onClick={() => syncAll()}
                        >
                            Sync All
                        </LoadingButton>
                    ) : null
                }
            />

            {/* Toolbar: quick-sync picker + sort + filter */}
            {sources.length > 0 && (
                <div className="flex flex-wrap items-center gap-3 p-3 rounded-lg bg-surface border border-border">
                    <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
                        <label className="text-sm text-fg-muted">Sync folder</label>
                        <select
                            value={pickerSelection}
                            onChange={e => setPickerSelection(e.target.value)}
                            className="flex-1 sm:flex-none min-w-0 sm:min-w-[200px] px-3 py-1.5 rounded-lg bg-surface border border-border text-fg text-sm"
                        >
                            <option value="">Select a folder...</option>
                            {[...sources]
                                .sort((a, b) => (a.name || '').localeCompare(b.name || ''))
                                .map(s => (
                                    <option key={s.name} value={s.name}>
                                        {s.name}
                                    </option>
                                ))}
                        </select>
                        <LoadingButton
                            loading={pickerSelection ? syncingFolders.has(pickerSelection) : false}
                            loadingText="Syncing..."
                            variant="primary"
                            icon="sync"
                            disabled={!pickerSelection}
                            onClick={() => syncOne(pickerSelection)}
                        >
                            Sync
                        </LoadingButton>
                    </div>

                    <div className="flex items-center gap-2">
                        <label className="text-sm text-fg-muted">Sort</label>
                        <select
                            value={sortBy}
                            onChange={e => setSortBy(e.target.value)}
                            className="px-3 py-1.5 rounded-lg bg-surface border border-border text-fg text-sm"
                        >
                            {SORT_OPTIONS.map(o => (
                                <option key={o.value} value={o.value}>
                                    {o.label}
                                </option>
                            ))}
                        </select>
                    </div>

                    <div className="flex items-center gap-2">
                        <label className="text-sm text-fg-muted">Show</label>
                        <div className="flex gap-1">
                            {FILTER_OPTIONS.map(o => (
                                <Button
                                    key={o.value}
                                    variant={filterBy === o.value ? 'primary' : 'ghost'}
                                    size="small"
                                    onClick={() => setFilterBy(o.value)}
                                >
                                    {o.label}
                                </Button>
                            ))}
                        </div>
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

            {!isLoading && displayedSources.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {displayedSources.map((source, i) => (
                        <div
                            key={source.id || source.name || i}
                            className="p-4 rounded-xl bg-surface border border-border hover:border-brand-primary/50 transition-fast"
                        >
                            <div className="flex items-start gap-3">
                                <span className="material-symbols-outlined text-brand-primary mt-0.5">
                                    folder
                                </span>
                                <div className="flex-1 min-w-0">
                                    <h3 className="font-semibold text-fg truncate">
                                        {source.name}
                                    </h3>
                                    <p className="text-xs text-fg-subtle truncate mt-1">
                                        {source.location}
                                    </p>
                                    <div className="flex items-center gap-3 mt-2 text-sm text-fg-muted">
                                        <span className="flex items-center gap-1">
                                            <span className="material-symbols-outlined text-sm">
                                                description
                                            </span>
                                            {source.file_count || 0} files
                                        </span>
                                        {source.size_bytes > 0 && (
                                            <span className="flex items-center gap-1">
                                                <span className="material-symbols-outlined text-sm">
                                                    database
                                                </span>
                                                {formatSize(source.size_bytes)}
                                            </span>
                                        )}
                                    </div>
                                    <p className="text-xs text-fg-subtle mt-1">
                                        Last synced: {formatLastSynced(source._lastSyncedMs)}
                                    </p>
                                    <div className="mt-3">
                                        <LoadingButton
                                            loading={syncingFolders.has(source.name)}
                                            loadingText="Syncing..."
                                            variant="ghost"
                                            icon="sync"
                                            onClick={() => syncOne(source.name)}
                                        >
                                            Sync
                                        </LoadingButton>
                                    </div>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default PosterGDriveSearchPage;
