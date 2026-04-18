import React, { useState, useCallback, useMemo, useEffect } from 'react';
import { useSearch, SEARCH_TYPES } from '../../contexts/SearchCoordinatorContext.jsx';
import { useToast } from '../../contexts/ToastContext.jsx';
import { useApiMutation } from '../../hooks/useApiData.js';
import { mediaAPI } from '../../utils/api/media.js';
import { Modal } from '../../components/modals/Modal';
import { Button, IconButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const FILTER_STORAGE_KEY = 'chub_media_search_filters';

function loadSavedFilters() {
    try {
        const saved = localStorage.getItem(FILTER_STORAGE_KEY);
        if (saved) return JSON.parse(saved);
    } catch {
        /* ignore */
    }
    return null;
}

function saveFilters(filters) {
    try {
        localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(filters));
    } catch {
        /* ignore */
    }
}

const MediaSearchPage = () => {
    const toast = useToast();

    const saved = useMemo(() => loadSavedFilters(), []);
    const [filters, setFilters] = useState({
        type: saved?.type || 'all',
        sort: saved?.sort || 'title',
        order: saved?.order || 'asc',
        limit: 50,
        offset: 0,
    });

    // Persist filter changes (excluding offset/limit)
    useEffect(() => {
        saveFilters({ type: filters.type, sort: filters.sort, order: filters.order });
    }, [filters.type, filters.sort, filters.order]);
    const [expandedId, setExpandedId] = useState(null);
    const [deleteTarget, setDeleteTarget] = useState(null);

    const { execute: deleteItem, isLoading: isDeleting } = useApiMutation(
        () => mediaAPI.deleteMediaItem(deleteTarget?.id),
        { successMessage: 'Media item deleted' }
    );

    const searchFunction = useCallback(
        term =>
            mediaAPI.searchMedia({
                query: term,
                type: filters.type !== 'all' ? filters.type : undefined,
                sort: filters.sort,
                order: filters.order,
                limit: filters.limit,
                offset: filters.offset,
            }),
        [filters]
    );

    const { term, results, isSearching, hasResults, totalCount, search } = useSearch(
        SEARCH_TYPES.MEDIA,
        searchFunction
    );

    const items = useMemo(() => results?.data?.items || results?.items || [], [results]);
    const total = useMemo(
        () => results?.data?.total || results?.total || totalCount || 0,
        [results, totalCount]
    );

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await deleteItem();
            toast.success(`Deleted "${deleteTarget.title}"`);
            setDeleteTarget(null);
            if (term) search(term, { immediate: true });
        } catch {
            toast.error('Failed to delete media item');
        }
    };

    const toggleExpand = id => {
        setExpandedId(prev => (prev === id ? null : id));
    };

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Library Search"
                description="Search and discover content in your media collection."
                badge={2}
                icon="search"
            />
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-end gap-3">
                <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                    <select
                        className="px-3 py-2 rounded-lg bg-surface border border-border text-primary text-sm"
                        value={filters.type}
                        onChange={e =>
                            setFilters(prev => ({ ...prev, type: e.target.value, offset: 0 }))
                        }
                    >
                        <option value="all">All Types</option>
                        <option value="movie">Movies</option>
                        <option value="show">Shows</option>
                    </select>
                    <select
                        className="px-3 py-2 rounded-lg bg-surface border border-border text-primary text-sm"
                        value={filters.sort}
                        onChange={e => setFilters(prev => ({ ...prev, sort: e.target.value }))}
                    >
                        <option value="title">Title</option>
                        <option value="year">Year</option>
                        <option value="rating">Rating</option>
                    </select>
                </div>
            </div>

            {isSearching && <Spinner size="large" text="Searching..." center />}

            {!isSearching && !term && (
                <div className="text-center py-16 text-tertiary">
                    <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                        search
                    </span>
                    <p className="text-lg">Use the search bar above to find media</p>
                    <p className="text-sm mt-2">
                        Search by title across all your configured instances
                    </p>
                </div>
            )}

            {!isSearching && term && !hasResults && (
                <div className="text-center py-16 text-tertiary">
                    <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                        search_off
                    </span>
                    <p className="text-lg">No results found for &quot;{term}&quot;</p>
                </div>
            )}

            {hasResults && (
                <>
                    <p className="text-sm text-secondary">
                        Found {total} result{total !== 1 ? 's' : ''} for &quot;{term}&quot;
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                        {items.map(item => (
                            <div
                                key={item.id}
                                className="rounded-xl bg-surface border border-border hover:border-brand-primary/50 transition-fast overflow-hidden group"
                            >
                                <div
                                    className="p-4 cursor-pointer"
                                    onClick={() => toggleExpand(item.id)}
                                >
                                    <div className="flex items-start justify-between mb-2">
                                        <h3 className="font-semibold text-primary truncate flex-1">
                                            {item.title}
                                        </h3>
                                        <div className="flex items-center gap-1 flex-shrink-0">
                                            <IconButton
                                                icon="delete"
                                                aria-label="Delete"
                                                variant="ghost"
                                                className="opacity-0 group-hover:opacity-100 transition-fast"
                                                onClick={e => {
                                                    e.stopPropagation();
                                                    setDeleteTarget(item);
                                                }}
                                            />
                                            {item.matched ? (
                                                <span className="ml-1 px-2 py-0.5 text-xs rounded-full bg-success/20 text-success">
                                                    Matched
                                                </span>
                                            ) : (
                                                <span className="ml-1 px-2 py-0.5 text-xs rounded-full bg-warning/20 text-warning">
                                                    Unmatched
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2 text-sm text-secondary">
                                        {item.year && <span>{item.year}</span>}
                                        {item.asset_type && (
                                            <span className="px-1.5 py-0.5 rounded bg-surface-alt text-xs capitalize">
                                                {item.asset_type}
                                            </span>
                                        )}
                                        {item.instance_name && (
                                            <span className="text-tertiary">
                                                {item.instance_name}
                                            </span>
                                        )}
                                    </div>
                                    {item.genre && (
                                        <p className="text-xs text-tertiary mt-2 truncate">
                                            {item.genre}
                                        </p>
                                    )}
                                </div>

                                {expandedId === item.id && (
                                    <div className="px-4 pb-4 border-t border-border pt-3 space-y-2">
                                        {item.path && (
                                            <p className="text-xs text-tertiary truncate">
                                                <span className="text-secondary">Path:</span>{' '}
                                                {item.path}
                                            </p>
                                        )}
                                        {item.rating != null && (
                                            <p className="text-xs text-tertiary">
                                                <span className="text-secondary">Rating:</span>{' '}
                                                {item.rating}
                                            </p>
                                        )}
                                        {item.added_at && (
                                            <p className="text-xs text-tertiary">
                                                <span className="text-secondary">Added:</span>{' '}
                                                {new Date(item.added_at).toLocaleDateString()}
                                            </p>
                                        )}
                                        <div className="pt-2">
                                            <Button
                                                variant="danger"
                                                icon="delete"
                                                onClick={e => {
                                                    e.stopPropagation();
                                                    setDeleteTarget(item);
                                                }}
                                            >
                                                Delete
                                            </Button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>

                    {total > filters.limit && (
                        <div className="flex items-center justify-center gap-4 mt-4">
                            <Button
                                variant="ghost"
                                onClick={() =>
                                    setFilters(prev => ({
                                        ...prev,
                                        offset: Math.max(0, prev.offset - prev.limit),
                                    }))
                                }
                                disabled={filters.offset === 0}
                            >
                                Previous
                            </Button>
                            <span className="text-sm text-secondary">
                                Page {Math.floor(filters.offset / filters.limit) + 1} of{' '}
                                {Math.ceil(total / filters.limit)}
                            </span>
                            <Button
                                variant="ghost"
                                onClick={() =>
                                    setFilters(prev => ({
                                        ...prev,
                                        offset: prev.offset + prev.limit,
                                    }))
                                }
                                disabled={filters.offset + filters.limit >= total}
                            >
                                Next
                            </Button>
                        </div>
                    )}
                </>
            )}

            <Modal isOpen={!!deleteTarget} onClose={() => setDeleteTarget(null)} size="small">
                <Modal.Header>Delete Media Item</Modal.Header>
                <Modal.Body>
                    <p className="text-secondary">
                        Are you sure you want to delete{' '}
                        <span className="font-semibold text-primary">{deleteTarget?.title}</span>?
                        This action cannot be undone.
                    </p>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
                        Cancel
                    </Button>
                    <Button
                        variant="danger"
                        icon="delete"
                        onClick={handleDelete}
                        disabled={isDeleting}
                    >
                        {isDeleting ? 'Deleting...' : 'Delete'}
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default MediaSearchPage;
