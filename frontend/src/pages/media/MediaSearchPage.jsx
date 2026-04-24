import React, { useState, useCallback, useMemo, useEffect } from 'react';
import PropTypes from 'prop-types';
import { useSearch, SEARCH_TYPES } from '../../contexts/SearchCoordinatorContext.jsx';
import { useToast } from '../../contexts/ToastContext.jsx';
import { useApiMutation } from '../../hooks/useApiData.js';
import { mediaAPI } from '../../utils/api/media.js';
import { Modal } from '../../components/modals/Modal';
import { Button, IconButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';
import RecentQueries, { useRecentQueries } from '../../components/RecentQueries.jsx';

const POSTER_FALLBACK_STYLE = {
    width: 80,
    height: 120,
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
};

function PosterThumb({ mediaId }) {
    const [errored, setErrored] = useState(false);
    const src = mediaAPI.getPosterUrl(mediaId);
    if (errored || !src) {
        return (
            <div className="rounded-md bg-surface-alt text-tertiary" style={POSTER_FALLBACK_STYLE}>
                <span className="material-symbols-outlined opacity-40">image</span>
            </div>
        );
    }
    return (
        <img
            src={src}
            alt=""
            loading="lazy"
            onError={() => setErrored(true)}
            className="rounded-md bg-surface-alt object-cover"
            style={{ width: 80, height: 120, flexShrink: 0 }}
        />
    );
}

PosterThumb.propTypes = {
    mediaId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
};

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

    const recent = useRecentQueries('chub_media_search_recent');
    useEffect(() => {
        if (term && hasResults) recent.record(term);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [term, hasResults]);

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

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Library Search"
                description="Search and discover content in your media collection."
                badge={2}
                icon="search"
                actions={
                    <div className="flex flex-wrap items-center gap-2">
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
                }
            />

            {isSearching && <Spinner size="large" text="Searching..." center />}

            {!isSearching && !term && (
                <div className="flex flex-col items-center gap-6 py-10 text-tertiary">
                    <div className="text-center">
                        <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                            search
                        </span>
                        <p className="text-lg">Use the search bar above to find media</p>
                        <p className="text-sm mt-2">
                            Search by title across all your configured instances
                        </p>
                    </div>
                    {recent.entries.length > 0 && (
                        <RecentQueries
                            entries={recent.entries}
                            onSelect={q => search(q, { immediate: true })}
                            onClear={recent.clear}
                            label="Recent searches"
                        />
                    )}
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
                    <div className="flex flex-col gap-3">
                        {items.map(item => (
                            <div
                                key={item.id}
                                className="rounded-xl bg-surface border border-border hover:border-brand-primary/50 transition-fast p-4 group"
                            >
                                <div className="flex items-start gap-4">
                                    <PosterThumb mediaId={item.id} />
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-start justify-between gap-3 mb-2">
                                            <h3 className="font-semibold text-primary text-lg">
                                                {item.title}
                                            </h3>
                                            <div className="flex items-center gap-2 flex-shrink-0">
                                                {item.matched ? (
                                                    <span className="px-2 py-0.5 text-xs rounded-full bg-success/20 text-success">
                                                        Matched
                                                    </span>
                                                ) : (
                                                    <span className="px-2 py-0.5 text-xs rounded-full bg-warning/20 text-warning">
                                                        Unmatched
                                                    </span>
                                                )}
                                                <IconButton
                                                    icon="delete"
                                                    aria-label="Delete"
                                                    variant="ghost"
                                                    className="opacity-0 group-hover:opacity-100 transition-fast"
                                                    onClick={() => setDeleteTarget(item)}
                                                />
                                            </div>
                                        </div>
                                        <div className="flex flex-wrap items-center gap-2 text-sm text-secondary mb-2">
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
                                            {item.rating != null && (
                                                <span className="text-tertiary">
                                                    ★ {item.rating}
                                                </span>
                                            )}
                                        </div>
                                        {item.genre && (
                                            <p className="text-xs text-tertiary mb-1">
                                                {item.genre}
                                            </p>
                                        )}
                                        {item.path && (
                                            <p className="text-xs text-tertiary break-all">
                                                {item.path}
                                            </p>
                                        )}
                                        {item.added_at && (
                                            <p className="text-xs text-tertiary mt-1">
                                                Added {new Date(item.added_at).toLocaleDateString()}
                                            </p>
                                        )}
                                    </div>
                                </div>
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
