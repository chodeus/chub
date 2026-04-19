import React, { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useSearch, SEARCH_TYPES } from '../../contexts/SearchCoordinatorContext.jsx';
import { useToast } from '../../contexts/ToastContext.jsx';
import { useApiMutation } from '../../hooks/useApiData.js';
import { postersAPI } from '../../utils/api/posters.js';
import { LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const PosterGDriveSearchPage = () => {
    const toast = useToast();
    const [syncingFolders, setSyncingFolders] = useState(new Set());
    const initialLoadDone = useRef(false);

    const searchFunction = useCallback(term => postersAPI.searchGoogleDrive({ query: term }), []);

    const { term, results, isSearching, hasResults, search } = useSearch(
        SEARCH_TYPES.POSTERS,
        searchFunction
    );

    // Load all GDrive sources on mount (no search term = show all)
    useEffect(() => {
        if (!initialLoadDone.current) {
            initialLoadDone.current = true;
            search('');
        }
    }, [search]);

    const sources = useMemo(() => results?.data?.sources || [], [results]);

    // Declared after `sources` so the sync-all closure references a bound value.
    const { execute: syncAll, isLoading: isSyncingAll } = useApiMutation(
        () => {
            const allNames = sources.map(s => s.name);
            return postersAPI.syncGDriveFolders(allNames);
        },
        { successMessage: 'All folders synced' }
    );

    const handleSyncFolder = async folderName => {
        setSyncingFolders(prev => new Set([...prev, folderName]));
        try {
            await postersAPI.syncGDriveFolders([folderName]);
            toast.success(`Synced "${folderName}"`);
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

    const handleSyncAll = async () => {
        try {
            await syncAll();
        } catch {
            toast.error('Failed to sync all folders');
        }
    };

    const formatSize = bytes => {
        if (!bytes || bytes <= 0) return null;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
        return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
    };

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="GDrive Posters"
                description="Search for posters in your synced Google Drive folders."
                badge={1}
                icon="cloud"
                actions={
                    hasResults && sources.length > 0 ? (
                        <LoadingButton
                            loading={isSyncingAll}
                            loadingText="Syncing All..."
                            variant="primary"
                            icon="sync"
                            onClick={handleSyncAll}
                        >
                            Sync All
                        </LoadingButton>
                    ) : null
                }
            />

            {isSearching && <Spinner size="large" text="Searching GDrive..." center />}

            {!isSearching && !term && (
                <div className="text-center py-16 text-tertiary">
                    <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                        cloud_search
                    </span>
                    <p className="text-lg">Use the search bar above to search GDrive folders</p>
                    <p className="text-sm mt-2">Search by folder name or location</p>
                </div>
            )}

            {!isSearching && term && !hasResults && (
                <div className="text-center py-16 text-tertiary">
                    <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                        search_off
                    </span>
                    <p className="text-lg">No GDrive sources found for &quot;{term}&quot;</p>
                </div>
            )}

            {hasResults && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {sources.map((source, i) => (
                        <div
                            key={source.id || i}
                            className="p-4 rounded-xl bg-surface border border-border hover:border-brand-primary/50 transition-fast"
                        >
                            <div className="flex items-start gap-3">
                                <span className="material-symbols-outlined text-brand-primary mt-0.5">
                                    folder
                                </span>
                                <div className="flex-1 min-w-0">
                                    <h3 className="font-semibold text-primary truncate">
                                        {source.name}
                                    </h3>
                                    <p className="text-xs text-tertiary truncate mt-1">
                                        {source.location}
                                    </p>
                                    <div className="flex items-center gap-3 mt-2 text-sm text-secondary">
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
                                    {source.last_updated && (
                                        <p className="text-xs text-tertiary mt-1">
                                            Last synced:{' '}
                                            {source.last_updated?.length === 8
                                                ? `${source.last_updated.slice(0, 4)}-${source.last_updated.slice(4, 6)}-${source.last_updated.slice(6, 8)}`
                                                : source.last_updated}
                                        </p>
                                    )}
                                    <div className="mt-3">
                                        <LoadingButton
                                            loading={syncingFolders.has(source.name)}
                                            loadingText="Syncing..."
                                            variant="ghost"
                                            icon="sync"
                                            onClick={() => handleSyncFolder(source.name)}
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
