import React, { useState, useMemo, useRef, useCallback } from 'react';
import PropTypes from 'prop-types';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { useModuleExecution } from '../../hooks/useModuleExecution.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { Modal } from '../../components/modals/Modal';
import { Button, LoadingButton, IconButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

function PosterThumbnail({ src, alt }) {
    const [errored, setErrored] = useState(false);
    if (errored) {
        return (
            <div className="w-full h-full flex items-center justify-center text-tertiary">
                <span className="material-symbols-outlined text-3xl">image</span>
            </div>
        );
    }
    return (
        <img
            src={src}
            alt={alt}
            className="w-full h-full object-cover"
            loading="lazy"
            onError={() => setErrored(true)}
        />
    );
}

PosterThumbnail.propTypes = {
    src: PropTypes.string.isRequired,
    alt: PropTypes.string,
};

const PAGE_SIZE = 60;
const STORAGE_KEY = 'chub_poster_assets_filters';

function loadSavedFilters() {
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) return JSON.parse(saved);
    } catch {
        /* ignore */
    }
    return null;
}

function saveFilters(filters) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
    } catch {
        /* ignore */
    }
}

const PosterAssetsSearchPage = () => {
    const toast = useToast();
    const { isRunning } = useModuleExecution();
    const fileInputRef = useRef(null);

    const [deleteTarget, setDeleteTarget] = useState(null);
    const [resolveTarget, setResolveTarget] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
    const [analyzeModal, setAnalyzeModal] = useState(null);
    const [showCreateCollection, setShowCreateCollection] = useState(false);
    const [newCollectionName, setNewCollectionName] = useState('');
    const [downloadTarget, setDownloadTarget] = useState(null);
    const [downloadOpts, setDownloadOpts] = useState({ size: '', format: '', quality: '85' });
    const [addToCollectionTarget, setAddToCollectionTarget] = useState(null);
    const [selectedCollectionId, setSelectedCollectionId] = useState('');
    const [expandedCollection, setExpandedCollection] = useState(null);
    const [lightboxItem, setLightboxItem] = useState(null);

    // Filter state — restore from localStorage if available
    const saved = useMemo(() => loadSavedFilters(), []);
    const [owner, setOwner] = useState(saved?.owner || '');
    const [type, setType] = useState(saved?.type || '');
    const [search, setSearch] = useState(saved?.search || '');
    const [offset, setOffset] = useState(0);

    // Track whether the user has active filters (page is blank without them)
    const hasFilters = !!(owner || type || search);

    const browseParams = useMemo(
        () => ({
            owner: owner || undefined,
            type: type || undefined,
            query: search || undefined,
            limit: PAGE_SIZE,
            offset,
        }),
        [owner, type, search, offset]
    );

    const {
        data: browseData,
        isLoading,
        refresh: refreshBrowse,
    } = useApiData({
        apiFunction: useCallback(
            () =>
                hasFilters
                    ? postersAPI.browsePosters(browseParams)
                    : postersAPI.browsePosters({ limit: 0 }),
            [browseParams, hasFilters]
        ),
        options: { showErrorToast: false },
    });

    const { data: dupData, refresh: refreshDups } = useApiData({
        apiFunction: postersAPI.fetchDuplicates,
        options: { showErrorToast: false },
    });

    const { execute: autoMatch, isLoading: isAutoMatching } = useApiMutation(
        () => postersAPI.autoMatchPosters(),
        { successMessage: 'Auto-match completed' }
    );

    const { execute: deleteItem, isLoading: isDeleting } = useApiMutation(
        () => postersAPI.deletePoster(deleteTarget?.id),
        { successMessage: 'Poster deleted' }
    );

    const { execute: resolveGroup, isLoading: isResolving } = useApiMutation(
        () => postersAPI.resolveDuplicates(resolveTarget?.id, { action: 'auto' }),
        { successMessage: 'Duplicate group resolved' }
    );

    const { execute: runAnalyze, isLoading: isAnalyzing } = useApiMutation(
        () => postersAPI.analyzeDirectory(),
        { successMessage: 'Directory analyzed' }
    );

    const { execute: runOptimize, isLoading: isOptimizing } = useApiMutation(
        () => postersAPI.optimizeStorage({ mode: 'optimize' }),
        { successMessage: 'Poster optimization started' }
    );

    const { execute: runSyncMetadata, isLoading: isSyncingMetadata } = useApiMutation(
        () => postersAPI.syncMetadata(),
        {
            successMessage: 'Metadata sync completed',
            onSuccess: () => refreshBrowse(),
        }
    );

    const { execute: createPosterCollection, isLoading: isCreatingPosterCollection } =
        useApiMutation(name => postersAPI.createCollection({ name }), {
            successMessage: 'Collection created',
            onSuccess: () => {
                setShowCreateCollection(false);
                setNewCollectionName('');
                refreshCollections();
            },
        });

    const { data: collectionsData, refresh: refreshCollections } = useApiData({
        apiFunction: postersAPI.fetchCollections,
        options: { showErrorToast: false },
    });

    const items = useMemo(() => browseData?.data?.items || [], [browseData]);
    const total = useMemo(() => browseData?.data?.total || 0, [browseData]);
    const owners = useMemo(() => browseData?.data?.owners || [], [browseData]);
    const duplicates = useMemo(() => dupData?.data?.duplicates || [], [dupData]);
    const collections = useMemo(
        () => collectionsData?.data?.collections || collectionsData?.data || [],
        [collectionsData]
    );

    const totalPages = Math.ceil(total / PAGE_SIZE);
    const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

    const handleFilterChange = (setter, key) => e => {
        const val = e.target.value;
        setter(val);
        setOffset(0);
        const current = loadSavedFilters() || {};
        saveFilters({ ...current, [key]: val });
    };

    const handleSearchChange = e => {
        setSearch(e.target.value);
    };

    const handleSearchKeyDown = e => {
        if (e.key === 'Enter') {
            setOffset(0);
            const current = loadSavedFilters() || {};
            saveFilters({ ...current, search });
        }
    };

    const handleAutoMatch = async () => {
        try {
            await autoMatch();
            refreshBrowse();
        } catch {
            toast.error('Auto-match failed');
        }
    };

    const handleUpload = async event => {
        const file = event.target.files?.[0];
        if (!file) return;

        setIsUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);
            await postersAPI.uploadPoster(formData);
            toast.success(`Uploaded "${file.name}"`);
            refreshBrowse();
        } catch {
            toast.error('Upload failed');
        } finally {
            setIsUploading(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await deleteItem();
            setDeleteTarget(null);
            refreshBrowse();
        } catch {
            toast.error('Failed to delete poster');
        }
    };

    const handleResolve = async () => {
        if (!resolveTarget) return;
        try {
            await resolveGroup();
            setResolveTarget(null);
            refreshDups();
        } catch {
            toast.error('Failed to resolve duplicates');
        }
    };

    const handleAnalyze = async () => {
        try {
            const result = await runAnalyze();
            const data = result?.data || result || {};
            const fileCount = data.file_count || data.count || 0;
            const totalBytes = data.size_bytes || data.total_size || 0;
            const totalMB = (totalBytes / (1024 * 1024)).toFixed(2);
            setAnalyzeModal({ fileCount, totalMB });
        } catch {
            toast.error('Directory analysis failed');
        }
    };

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Assets Search"
                description={`Browse and manage posters in your local asset cache (${total} posters).`}
                badge={2}
                icon="folder"
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        <LoadingButton
                            loading={isRunning('poster_renamerr') || isAutoMatching}
                            loadingText="Matching..."
                            variant="ghost"
                            icon="auto_fix_high"
                            onClick={handleAutoMatch}
                            title="Run Poster Renamerr to automatically match poster files to media items"
                        >
                            Auto-Match
                        </LoadingButton>
                        <LoadingButton
                            loading={isAnalyzing}
                            loadingText="Analyzing..."
                            variant="ghost"
                            icon="analytics"
                            onClick={handleAnalyze}
                            title="Scan the poster directory and report file count and total storage size"
                        >
                            Analyze
                        </LoadingButton>
                        <LoadingButton
                            loading={isOptimizing}
                            loadingText="Optimizing..."
                            variant="ghost"
                            icon="tune"
                            onClick={() => runOptimize()}
                            title="Resize oversized posters and compress images to save disk space"
                        >
                            Optimize
                        </LoadingButton>
                        <LoadingButton
                            loading={isSyncingMetadata}
                            loadingText="Syncing..."
                            variant="ghost"
                            icon="sync"
                            onClick={() => runSyncMetadata()}
                            title="Refresh poster metadata by running a full Poster Renamerr sync"
                        >
                            Sync Metadata
                        </LoadingButton>
                        <LoadingButton
                            loading={isUploading}
                            loadingText="Uploading..."
                            variant="primary"
                            icon="upload"
                            onClick={() => fileInputRef.current?.click()}
                            title="Upload a poster image file"
                        >
                            Upload
                        </LoadingButton>
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept="image/*"
                            className="hidden"
                            onChange={handleUpload}
                        />
                    </div>
                }
            />

            {/* Filters */}
            <div className="flex items-center gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                    <label className="text-sm text-secondary">Owner</label>
                    <select
                        value={owner}
                        onChange={handleFilterChange(setOwner, 'owner')}
                        className="px-3 py-1.5 rounded-lg bg-surface border border-border text-primary text-sm"
                    >
                        <option value="">All</option>
                        {owners.map(o => (
                            <option key={o} value={o}>
                                {o}
                            </option>
                        ))}
                    </select>
                </div>
                <div className="flex items-center gap-2">
                    <label className="text-sm text-secondary">Type</label>
                    <select
                        value={type}
                        onChange={handleFilterChange(setType, 'type')}
                        className="px-3 py-1.5 rounded-lg bg-surface border border-border text-primary text-sm"
                    >
                        <option value="">All</option>
                        <option value="movie">Movies</option>
                        <option value="season">Seasons</option>
                    </select>
                </div>
                <div
                    className="flex items-center gap-2 flex-1 max-w-sm"
                    style={{ minWidth: '200px' }}
                >
                    <label className="text-sm text-secondary">Search</label>
                    <input
                        type="text"
                        value={search}
                        onChange={handleSearchChange}
                        onKeyDown={handleSearchKeyDown}
                        placeholder="Search by title..."
                        className="w-full px-3 py-1.5 rounded-lg bg-surface border border-border text-primary text-sm placeholder:text-tertiary"
                    />
                </div>
            </div>

            {/* Duplicates */}
            {duplicates.length > 0 && (
                <section>
                    <h3 className="text-lg font-semibold text-primary mb-3 flex items-center gap-2">
                        <span className="material-symbols-outlined text-warning">content_copy</span>
                        Duplicates ({duplicates.length} groups)
                    </h3>
                    <div className="grid gap-2">
                        {duplicates.slice(0, 10).map((dup, i) => (
                            <div
                                key={dup.id || i}
                                className="p-3 rounded-lg bg-surface border border-border flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2"
                            >
                                <div className="flex items-center flex-wrap gap-2 min-w-0">
                                    <span className="font-medium text-primary truncate">
                                        {dup.normalized_title}
                                    </span>
                                    {dup.year && (
                                        <span className="text-secondary flex-shrink-0">
                                            ({dup.year})
                                        </span>
                                    )}
                                    {dup.season_number != null && (
                                        <span className="text-tertiary flex-shrink-0">
                                            S{String(dup.season_number).padStart(2, '0')}
                                        </span>
                                    )}
                                </div>
                                <div className="flex items-center flex-wrap gap-2 sm:gap-3">
                                    <span className="text-sm font-medium text-warning">
                                        {dup.count} copies
                                    </span>
                                    <Button
                                        variant="ghost"
                                        icon="auto_fix_high"
                                        onClick={() => setResolveTarget(dup)}
                                    >
                                        Resolve
                                    </Button>
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}

            {/* Collections */}
            {Array.isArray(collections) && collections.length > 0 && (
                <section>
                    <h3 className="text-lg font-semibold text-primary mb-3 flex items-center gap-2">
                        <span className="material-symbols-outlined text-brand-primary">
                            collections_bookmark
                        </span>
                        Collections ({collections.length})
                        <Button
                            variant="ghost"
                            icon="add"
                            onClick={() => setShowCreateCollection(true)}
                        >
                            Create
                        </Button>
                    </h3>
                    <div className="grid gap-2">
                        {collections.map((col, i) => (
                            <div key={col.id || i}>
                                <div
                                    className="p-3 rounded-lg bg-surface border border-border flex items-center justify-between cursor-pointer hover:bg-surface-alt"
                                    onClick={() =>
                                        setExpandedCollection(
                                            expandedCollection === col.id ? null : col.id
                                        )
                                    }
                                >
                                    <div className="flex items-center gap-2">
                                        <span className="material-symbols-outlined text-sm text-secondary">
                                            {expandedCollection === col.id
                                                ? 'expand_less'
                                                : 'expand_more'}
                                        </span>
                                        <span className="font-medium text-primary truncate">
                                            {col.name || col.title}
                                        </span>
                                        {col.poster_count != null && (
                                            <span className="text-xs text-tertiary">
                                                ({col.poster_count} posters)
                                            </span>
                                        )}
                                    </div>
                                </div>
                                {expandedCollection === col.id &&
                                    Array.isArray(col.posters) &&
                                    col.posters.length > 0 && (
                                        <div className="ml-6 mt-1 space-y-1">
                                            {col.posters.map(poster => (
                                                <div
                                                    key={poster.id}
                                                    className="flex items-center justify-between p-2 rounded bg-surface-alt text-sm"
                                                >
                                                    <span className="text-primary truncate">
                                                        {poster.title ||
                                                            poster.file ||
                                                            `#${poster.id}`}
                                                    </span>
                                                    <IconButton
                                                        icon="remove_circle_outline"
                                                        aria-label="Remove from collection"
                                                        title="Remove this poster from the collection (poster stays in your library)"
                                                        variant="ghost"
                                                        onClick={async e => {
                                                            e.stopPropagation();
                                                            try {
                                                                await postersAPI.removeFromCollection(
                                                                    col.id,
                                                                    poster.id
                                                                );
                                                                toast.success(
                                                                    'Removed from collection'
                                                                );
                                                                refreshCollections();
                                                            } catch {
                                                                toast.error(
                                                                    'Failed to remove from collection'
                                                                );
                                                            }
                                                        }}
                                                    />
                                                </div>
                                            ))}
                                        </div>
                                    )}
                            </div>
                        ))}
                    </div>
                </section>
            )}

            {/* Poster Grid */}
            {isLoading ? (
                <Spinner size="large" text="Loading posters..." center />
            ) : items.length > 0 ? (
                <section>
                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-3">
                        <h3 className="text-lg font-semibold text-primary">Posters ({total})</h3>
                        {totalPages > 1 && (
                            <div className="flex flex-wrap items-center gap-2">
                                <Button
                                    variant="ghost"
                                    size="small"
                                    disabled={offset === 0}
                                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                                >
                                    Previous
                                </Button>
                                <span className="text-sm text-secondary">
                                    Page {currentPage} of {totalPages}
                                </span>
                                <Button
                                    variant="ghost"
                                    size="small"
                                    disabled={offset + PAGE_SIZE >= total}
                                    onClick={() => setOffset(offset + PAGE_SIZE)}
                                >
                                    Next
                                </Button>
                            </div>
                        )}
                    </div>
                    <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-7 xl:grid-cols-8 gap-3">
                        {items.map(item => {
                            const suffixParts = [
                                item.year,
                                item.season_number != null
                                    ? `S${String(item.season_number).padStart(2, '0')}`
                                    : null,
                            ].filter(Boolean);
                            const displayTitle = suffixParts.length
                                ? `${item.title} (${suffixParts.join(' ')})`
                                : item.title;
                            return (
                                <div
                                    key={item.id}
                                    className="relative rounded-lg bg-surface border border-border overflow-hidden group flex flex-col"
                                >
                                    {(item.folder || item.file) && (
                                        <button
                                            type="button"
                                            onClick={() => setLightboxItem(item)}
                                            className="bg-surface-alt overflow-hidden block w-full p-0 border-0 cursor-zoom-in"
                                            style={{ aspectRatio: '2 / 3' }}
                                            aria-label={`Enlarge ${displayTitle}`}
                                        >
                                            <PosterThumbnail
                                                src={
                                                    item.id
                                                        ? postersAPI.getThumbnailUrl(item.id, 200)
                                                        : postersAPI.getPreviewUrl(
                                                              item.folder,
                                                              item.file
                                                          )
                                                }
                                                alt={displayTitle}
                                            />
                                        </button>
                                    )}
                                    <div className="absolute top-1.5 right-1.5 z-10 flex items-center gap-0.5 rounded-lg bg-black/55 backdrop-blur-sm p-0.5 opacity-0 group-hover:opacity-100 transition-fast">
                                        <IconButton
                                            icon="playlist_add"
                                            aria-label="Add to collection"
                                            title="Add this poster to an existing or new collection"
                                            variant="ghost"
                                            size="small"
                                            onClick={() => setAddToCollectionTarget(item)}
                                        />
                                        <IconButton
                                            icon="download"
                                            aria-label="Download poster"
                                            title="Download the poster image"
                                            variant="ghost"
                                            size="small"
                                            onClick={() => setDownloadTarget(item)}
                                        />
                                        <IconButton
                                            icon="delete"
                                            aria-label="Delete poster"
                                            title="Delete this poster file from the server"
                                            variant="ghost"
                                            size="small"
                                            onClick={() => setDeleteTarget(item)}
                                        />
                                    </div>
                                    <div className="p-1.5">
                                        <h4
                                            className="font-medium text-primary text-xs line-clamp-2 break-words leading-tight text-center"
                                            title={displayTitle}
                                        >
                                            {displayTitle}
                                        </h4>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                    {/* Bottom pagination */}
                    {totalPages > 1 && (
                        <div className="flex items-center justify-center gap-2 mt-4">
                            <Button
                                variant="ghost"
                                size="small"
                                disabled={offset === 0}
                                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                            >
                                Previous
                            </Button>
                            <span className="text-sm text-secondary">
                                Page {currentPage} of {totalPages}
                            </span>
                            <Button
                                variant="ghost"
                                size="small"
                                disabled={offset + PAGE_SIZE >= total}
                                onClick={() => setOffset(offset + PAGE_SIZE)}
                            >
                                Next
                            </Button>
                        </div>
                    )}
                </section>
            ) : (
                <div className="text-center py-16 text-tertiary">
                    <span className="material-symbols-outlined text-5xl mb-4 block opacity-40">
                        {hasFilters ? 'search_off' : 'filter_alt'}
                    </span>
                    <p className="text-lg">
                        {hasFilters ? 'No posters found' : 'Select a filter to browse posters'}
                    </p>
                    <p className="text-sm mt-2">
                        {hasFilters
                            ? 'Try adjusting your filters'
                            : 'Use the owner, type, or search filters above to get started'}
                    </p>
                </div>
            )}

            {/* Lightbox */}
            <Modal isOpen={!!lightboxItem} onClose={() => setLightboxItem(null)} size="large">
                <Modal.Header>
                    <span
                        className="block text-base font-semibold text-primary break-words pr-2"
                        title={[
                            lightboxItem?.title,
                            lightboxItem?.year ? `(${lightboxItem.year})` : '',
                            lightboxItem?.season_number != null
                                ? `— S${String(lightboxItem.season_number).padStart(2, '0')}`
                                : '',
                        ]
                            .filter(Boolean)
                            .join(' ')}
                    >
                        {lightboxItem?.title}
                        {lightboxItem?.year && ` (${lightboxItem.year})`}
                        {lightboxItem?.season_number != null &&
                            ` — S${String(lightboxItem.season_number).padStart(2, '0')}`}
                    </span>
                </Modal.Header>
                <Modal.Body>
                    {lightboxItem && (
                        <div className="flex items-center justify-center bg-surface-alt rounded-lg p-2">
                            <img
                                // Full-resolution original. Backend thumbnail
                                // endpoint caps width at 500 and 422s anything
                                // larger, so the lightbox uses the preview path
                                // (serves the raw file, no resize) instead.
                                src={
                                    lightboxItem.folder && lightboxItem.file
                                        ? postersAPI.getPreviewUrl(
                                              lightboxItem.folder,
                                              lightboxItem.file
                                          )
                                        : postersAPI.getThumbnailUrl(lightboxItem.id, 500)
                                }
                                alt={lightboxItem.title}
                                className="w-auto object-contain"
                                style={{ maxHeight: '75vh' }}
                            />
                        </div>
                    )}
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setLightboxItem(null)}>
                        Close
                    </Button>
                    {lightboxItem && (
                        <Button
                            variant="primary"
                            icon="download"
                            onClick={() => {
                                setDownloadTarget(lightboxItem);
                                setLightboxItem(null);
                            }}
                        >
                            Download
                        </Button>
                    )}
                </Modal.Footer>
            </Modal>

            <Modal isOpen={!!deleteTarget} onClose={() => setDeleteTarget(null)} size="small">
                <Modal.Header>Delete Poster</Modal.Header>
                <Modal.Body>
                    <p className="text-secondary">
                        Are you sure you want to delete the poster for{' '}
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

            <Modal isOpen={!!resolveTarget} onClose={() => setResolveTarget(null)} size="small">
                <Modal.Header>Resolve Duplicates</Modal.Header>
                <Modal.Body>
                    <p className="text-secondary">
                        Resolve the duplicate group for{' '}
                        <span className="font-semibold text-primary">
                            {resolveTarget?.normalized_title}
                        </span>
                        ? This will automatically keep the best match and remove extras.
                    </p>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setResolveTarget(null)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        icon="auto_fix_high"
                        onClick={handleResolve}
                        disabled={isResolving}
                    >
                        {isResolving ? 'Resolving...' : 'Resolve'}
                    </Button>
                </Modal.Footer>
            </Modal>

            <Modal isOpen={!!analyzeModal} onClose={() => setAnalyzeModal(null)} size="small">
                <Modal.Header>Directory Analysis</Modal.Header>
                <Modal.Body>
                    <div className="space-y-3">
                        <div className="flex items-center justify-between p-3 rounded-lg bg-surface-alt">
                            <span className="text-secondary">Files Found</span>
                            <span className="font-semibold text-primary">
                                {analyzeModal?.fileCount}
                            </span>
                        </div>
                        <div className="flex items-center justify-between p-3 rounded-lg bg-surface-alt">
                            <span className="text-secondary">Total Size</span>
                            <span className="font-semibold text-primary">
                                {analyzeModal?.totalMB} MB
                            </span>
                        </div>
                    </div>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setAnalyzeModal(null)}>
                        Close
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* Create Collection Modal */}
            <Modal
                isOpen={showCreateCollection}
                onClose={() => {
                    setShowCreateCollection(false);
                    setNewCollectionName('');
                }}
                size="small"
            >
                <Modal.Header>Create Poster Collection</Modal.Header>
                <Modal.Body>
                    <label className="block text-sm text-secondary mb-1">Collection Name</label>
                    <input
                        type="text"
                        value={newCollectionName}
                        onChange={e => setNewCollectionName(e.target.value)}
                        placeholder="My Collection"
                        className="w-full p-2 bg-input border border-border rounded-md text-primary text-sm focus:border-primary focus:outline-none"
                    />
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setShowCreateCollection(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        icon="add"
                        onClick={() => createPosterCollection(newCollectionName.trim())}
                        disabled={isCreatingPosterCollection || !newCollectionName.trim()}
                    >
                        {isCreatingPosterCollection ? 'Creating...' : 'Create'}
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* Download Options Modal */}
            <Modal
                isOpen={!!downloadTarget}
                onClose={() => {
                    setDownloadTarget(null);
                    setDownloadOpts({ size: '', format: '', quality: '85' });
                }}
                size="small"
            >
                <Modal.Header>Download Poster</Modal.Header>
                <Modal.Body>
                    <p className="text-sm text-secondary mb-3">
                        {downloadTarget?.title || 'Poster'} — configure download options
                    </p>
                    <div className="space-y-3">
                        <div>
                            <label className="block text-xs text-secondary mb-1">
                                Size (width in px, blank for original)
                            </label>
                            <input
                                type="number"
                                value={downloadOpts.size}
                                onChange={e =>
                                    setDownloadOpts(prev => ({ ...prev, size: e.target.value }))
                                }
                                placeholder="e.g. 500"
                                className="w-full p-2 bg-input border border-border rounded-md text-primary text-sm focus:border-primary focus:outline-none"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-secondary mb-1">Format</label>
                            <select
                                value={downloadOpts.format}
                                onChange={e =>
                                    setDownloadOpts(prev => ({ ...prev, format: e.target.value }))
                                }
                                className="w-full p-2 bg-input border border-border rounded-md text-primary text-sm cursor-pointer"
                            >
                                <option value="">Original</option>
                                <option value="webp">WebP</option>
                                <option value="jpg">JPEG</option>
                                <option value="png">PNG</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs text-secondary mb-1">
                                Quality (1-100)
                            </label>
                            <input
                                type="number"
                                min="1"
                                max="100"
                                value={downloadOpts.quality}
                                onChange={e =>
                                    setDownloadOpts(prev => ({ ...prev, quality: e.target.value }))
                                }
                                className="w-full p-2 bg-input border border-border rounded-md text-primary text-sm focus:border-primary focus:outline-none"
                            />
                        </div>
                    </div>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setDownloadTarget(null)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        icon="download"
                        onClick={async () => {
                            try {
                                const opts = {};
                                if (downloadOpts.size) opts.size = Number(downloadOpts.size);
                                if (downloadOpts.format) opts.format = downloadOpts.format;
                                if (downloadOpts.quality)
                                    opts.quality = Number(downloadOpts.quality);
                                await postersAPI.downloadPoster(downloadTarget.id, opts);
                                toast.success('Download started');
                                setDownloadTarget(null);
                            } catch {
                                toast.error('Download failed');
                            }
                        }}
                    >
                        Download
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* Add to Collection Modal */}
            <Modal
                isOpen={!!addToCollectionTarget}
                onClose={() => {
                    setAddToCollectionTarget(null);
                    setSelectedCollectionId('');
                }}
                size="small"
            >
                <Modal.Header>Add to Collection</Modal.Header>
                <Modal.Body>
                    <p className="text-sm text-secondary mb-3">
                        Add &ldquo;{addToCollectionTarget?.title || 'poster'}&rdquo; to a collection
                    </p>
                    <select
                        value={selectedCollectionId}
                        onChange={e => setSelectedCollectionId(e.target.value)}
                        className="w-full p-2 bg-input border border-border rounded-md text-primary text-sm cursor-pointer"
                    >
                        <option value="">Select a collection...</option>
                        {collections.map(col => (
                            <option key={col.id} value={col.id}>
                                {col.title || col.name}
                            </option>
                        ))}
                    </select>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setAddToCollectionTarget(null)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        icon="playlist_add"
                        disabled={!selectedCollectionId}
                        onClick={async () => {
                            try {
                                await postersAPI.addToCollection(
                                    selectedCollectionId,
                                    addToCollectionTarget.id
                                );
                                toast.success('Added to collection');
                                setAddToCollectionTarget(null);
                                setSelectedCollectionId('');
                                refreshCollections();
                            } catch {
                                toast.error('Failed to add to collection');
                            }
                        }}
                    >
                        Add
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default PosterAssetsSearchPage;
