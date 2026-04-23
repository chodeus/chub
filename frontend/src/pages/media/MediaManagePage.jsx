import React, { useState, useMemo, useEffect } from 'react';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { mediaAPI } from '../../utils/api/media.js';
import { nestarrAPI } from '../../utils/api/nestarr.js';
import { apiCore } from '../../utils/api/core.js';
import { Modal } from '../../components/modals/Modal';
import EditMediaModal from '../../components/modals/EditMediaModal.jsx';
import { Button, LoadingButton, IconButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';
import { LibraryMaintenance } from '../../components/maintenance/LibraryMaintenance.jsx';

const MediaManagePage = () => {
    const toast = useToast();
    const [deleteTarget, setDeleteTarget] = useState(null);
    const [deleteFiles, setDeleteFiles] = useState(false);
    const [editTarget, setEditTarget] = useState(null);
    const [resolveTarget, setResolveTarget] = useState(null);
    const [resolveKeepId, setResolveKeepId] = useState(null);
    const [resolveDeleteFiles, setResolveDeleteFiles] = useState(false);
    const [showImport, setShowImport] = useState(false);
    const [importText, setImportText] = useState('');
    const [showCreateCollection, setShowCreateCollection] = useState(false);
    const [newCollectionName, setNewCollectionName] = useState('');
    const [editCollection, setEditCollection] = useState(null);
    const [editCollectionName, setEditCollectionName] = useState('');
    const [nestedIssues, setNestedIssues] = useState([]);
    const [lastScanTime, setLastScanTime] = useState(null);
    const [fixTarget, setFixTarget] = useState(null);
    const [fixPreview, setFixPreview] = useState(null);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [page, setPage] = useState(0);
    const PAGE_SIZE = 100;

    const { execute: saveMetadata, isLoading: isSaving } = useApiMutation(
        (id, metadata) => mediaAPI.updateMediaMetadata(id, metadata),
        {
            successMessage: 'Metadata updated',
            onSuccess: () => {
                setEditTarget(null);
                refreshMedia();
            },
        }
    );

    const {
        data: mediaData,
        isLoading,
        refresh: refreshMedia,
    } = useApiData({
        apiFunction: () =>
            mediaAPI.searchMedia({
                limit: PAGE_SIZE,
                offset: page * PAGE_SIZE,
                sort: 'title',
                order: 'asc',
            }),
        options: { showErrorToast: false },
        dependencies: [page],
    });

    const { data: dupData, refresh: refreshDups } = useApiData({
        apiFunction: mediaAPI.fetchDuplicates,
        options: { showErrorToast: false },
    });

    const { execute: runExport, isLoading: isExporting } = useApiMutation(
        () => mediaAPI.exportMedia({ format: 'json' }),
        { successMessage: 'Export started successfully' }
    );

    const { execute: runScan, isLoading: isScanning } = useApiMutation(
        () => mediaAPI.scanForMedia(),
        {
            successMessage: 'Media scan initiated',
            onSuccess: () => {
                refreshMedia();
            },
        }
    );

    const { execute: runFixMetadata, isLoading: isFixing } = useApiMutation(
        () => mediaAPI.fixMetadata(),
        {
            successMessage: 'Metadata fix initiated',
            onSuccess: () => {
                refreshMedia();
            },
        }
    );

    const { execute: runImport, isLoading: isImporting } = useApiMutation(
        data => mediaAPI.importMedia(data),
        {
            successMessage: 'Media import started',
            onSuccess: () => {
                setShowImport(false);
                setImportText('');
                refreshMedia();
            },
        }
    );

    const { execute: createCollection, isLoading: isCreatingCollection } = useApiMutation(
        name => mediaAPI.createCollection({ name }),
        {
            successMessage: 'Collection created',
            onSuccess: () => {
                setShowCreateCollection(false);
                setNewCollectionName('');
                refreshCollections();
            },
        }
    );

    const { execute: updateCollectionMutation, isLoading: isUpdatingCollection } = useApiMutation(
        (id, data) => mediaAPI.updateCollection(id, data),
        {
            successMessage: 'Collection updated',
            onSuccess: () => {
                setEditCollection(null);
                setEditCollectionName('');
                refreshCollections();
            },
        }
    );

    const { data: collectionsData, refresh: refreshCollections } = useApiData({
        apiFunction: mediaAPI.fetchCollections,
        options: { showErrorToast: false },
    });

    const { execute: deleteCollection } = useApiMutation(id => mediaAPI.deleteCollection(id), {
        successMessage: 'Collection deleted',
    });

    const { execute: deleteItem, isLoading: isDeleting } = useApiMutation(
        () => mediaAPI.deleteMediaItem(deleteTarget?.id, { deleteFiles }),
        { successMessage: 'Media item deleted' }
    );

    const { execute: resolveGroup, isLoading: isResolving } = useApiMutation(
        () => {
            const ids = (resolveTarget?.ids || '').split(',').map(Number).filter(Boolean);
            const removeIds = ids.filter(id => id !== resolveKeepId);
            return mediaAPI.resolveDuplicates(resolveTarget?.normalized_title || '0', {
                keepId: resolveKeepId,
                removeIds,
                deleteFiles: resolveDeleteFiles,
            });
        },
        { successMessage: 'Duplicate group resolved' }
    );

    const { execute: runNestedScan, isLoading: isNestScanning } = useApiMutation(
        async () => {
            const result = await nestarrAPI.scan();
            setNestedIssues(result?.data?.issues || []);
            setLastScanTime(result?.data?.scanned_at || null);
            return result;
        },
        {
            successMessage: 'Nested media scan complete',
            onSuccess: () => {
                // Clear any stale nestarr cache so page re-mounts get fresh DB results
                apiCore.clearCache('/nestarr');
            },
        }
    );

    // Load cached nestarr scan results on mount
    useEffect(() => {
        nestarrAPI
            .getResults()
            .then(result => {
                const data = result?.data;
                if (data?.issues?.length > 0) {
                    setNestedIssues(data.issues);
                    setLastScanTime(data.scanned_at || null);
                }
            })
            .catch(() => {});
    }, []);

    const { execute: runNestedFix, isLoading: isNestFixing } = useApiMutation(
        params => nestarrAPI.fix(params),
        { successMessage: 'Nested media item moved successfully' }
    );

    const items = useMemo(() => mediaData?.data?.items || [], [mediaData]);
    const duplicates = useMemo(() => dupData?.data?.duplicates || [], [dupData]);
    const collections = useMemo(
        () => collectionsData?.data?.collections || collectionsData?.data || [],
        [collectionsData]
    );

    const { execute: runRefreshCache, isLoading: isRefreshing } = useApiMutation(
        () => mediaAPI.refreshLibrary(),
        {
            successMessage: 'Cache refresh initiated',
            onSuccess: () => {
                setPage(0);
                refreshMedia();
                refreshDups();
            },
        }
    );

    const handleRefreshCache = async () => {
        await runRefreshCache();
    };

    const handleExport = async () => {
        try {
            await runExport();
        } catch {
            toast.error('Export failed');
        }
    };

    const handleScan = async () => {
        try {
            await runScan();
        } catch {
            toast.error('Scan failed');
        }
    };

    const handleFixMetadata = async () => {
        try {
            await runFixMetadata();
        } catch {
            toast.error('Fix metadata failed');
        }
    };

    const handleNestedScan = async () => {
        try {
            await runNestedScan();
        } catch {
            toast.error('Nested media scan failed');
        }
    };

    const handlePreviewFix = async issue => {
        setFixTarget(issue);
        setFixPreview(null);
        setPreviewLoading(true);
        try {
            const result = await nestarrAPI.preview({
                instance_type: issue.nested.instance_type,
                instance_name: issue.nested.instance,
                media_id: issue.nested.media_id,
                target_path: issue.suggested_path,
            });
            setFixPreview(result?.data || null);
        } catch {
            toast.error('Failed to load preview');
            setFixTarget(null);
        } finally {
            setPreviewLoading(false);
        }
    };

    const handleNestedFix = async () => {
        if (!fixTarget) return;
        const targetId = fixTarget.id;
        try {
            await runNestedFix({
                instance_type: fixTarget.nested.instance_type,
                instance_name: fixTarget.nested.instance,
                media_id: fixTarget.nested.media_id,
                target_path: fixTarget.suggested_path,
            });
            setFixTarget(null);
            setFixPreview(null);
            setNestedIssues(prev => prev.filter(i => i.id !== targetId));
        } catch {
            toast.error('Failed to fix nested media');
        }
    };

    const handleImport = async () => {
        if (!importText.trim()) return;
        try {
            // Parse as JSON array or newline-separated titles
            let data;
            try {
                data = JSON.parse(importText);
            } catch {
                data = importText
                    .split('\n')
                    .map(l => l.trim())
                    .filter(Boolean)
                    .map(title => ({ title }));
            }
            await runImport(Array.isArray(data) ? data : [data]);
        } catch {
            toast.error('Import failed');
        }
    };

    const handleCreateCollection = async () => {
        if (!newCollectionName.trim()) return;
        try {
            await createCollection(newCollectionName.trim());
        } catch {
            toast.error('Failed to create collection');
        }
    };

    const handleDeleteCollection = async id => {
        try {
            await deleteCollection(id);
            refreshCollections();
        } catch {
            toast.error('Failed to delete collection');
        }
    };

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await deleteItem();
            setDeleteTarget(null);
            setDeleteFiles(false);
            refreshMedia();
        } catch {
            toast.error('Failed to delete media item');
        }
    };

    const handleResolve = async () => {
        if (!resolveTarget || !resolveKeepId) return;
        try {
            await resolveGroup();
            setResolveTarget(null);
            setResolveKeepId(null);
            setResolveDeleteFiles(false);
            refreshDups();
            refreshMedia();
        } catch {
            toast.error('Failed to resolve duplicates');
        }
    };

    if (isLoading) return <Spinner size="large" text="Loading media..." center />;

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Library Management"
                description="Manage and organize your media library."
                badge={3}
                icon="tune"
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        <LoadingButton
                            loading={isRefreshing}
                            loadingText="Refreshing..."
                            variant="ghost"
                            icon="refresh"
                            onClick={handleRefreshCache}
                            title="Re-sync all media from your Radarr and Sonarr instances into the local cache"
                        >
                            Refresh Cache
                        </LoadingButton>
                        <LoadingButton
                            loading={isExporting}
                            loadingText="Exporting..."
                            variant="ghost"
                            icon="download"
                            onClick={handleExport}
                            title="Download your media library data as a JSON file"
                        >
                            Export
                        </LoadingButton>
                        <LoadingButton
                            loading={isScanning}
                            loadingText="Scanning..."
                            variant="ghost"
                            icon="radar"
                            onClick={handleScan}
                            title="Scan for new media by refreshing the cache from all configured instances"
                        >
                            Scan
                        </LoadingButton>
                        <LoadingButton
                            loading={isFixing}
                            loadingText="Fixing..."
                            variant="ghost"
                            icon="build"
                            onClick={handleFixMetadata}
                            title="Re-fetch metadata from all instances and update Plex mappings"
                        >
                            Fix Metadata
                        </LoadingButton>
                        <Button
                            variant="primary"
                            icon="add"
                            onClick={() => setShowImport(true)}
                            title="Add media items manually by title or JSON data"
                        >
                            Import
                        </Button>
                    </div>
                }
            />

            {duplicates.length > 0 && (
                <section className="mb-4">
                    <h3 className="text-lg font-semibold text-primary mb-3 flex items-center gap-2">
                        <span className="material-symbols-outlined text-warning">content_copy</span>
                        Duplicates ({duplicates.length} groups)
                    </h3>
                    <div className="grid gap-2">
                        {duplicates.slice(0, 10).map((dup, i) => {
                            // Deduplicate instance names and format as badges
                            const uniqueInstances = dup.instances
                                ? [...new Set(dup.instances.split(','))]
                                      .map(s => s.trim())
                                      .filter(Boolean)
                                : [];
                            return (
                                <div
                                    key={dup.id || i}
                                    className="p-3 rounded-lg bg-surface border border-border flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2"
                                >
                                    <div className="flex items-center gap-2 min-w-0">
                                        <span className="font-medium text-primary truncate">
                                            {dup.title || dup.normalized_title}
                                        </span>
                                        {dup.year && (
                                            <span className="text-secondary flex-shrink-0">
                                                ({dup.year})
                                            </span>
                                        )}
                                    </div>
                                    <div className="flex items-center flex-wrap gap-2 sm:gap-3">
                                        <span className="text-sm font-medium text-warning">
                                            {dup.count} copies
                                        </span>
                                        <div className="flex items-center flex-wrap gap-1">
                                            {uniqueInstances.map(inst => (
                                                <span
                                                    key={inst}
                                                    className="text-xs px-2 py-0.5 rounded-full bg-surface-alt text-secondary"
                                                >
                                                    {inst}
                                                </span>
                                            ))}
                                        </div>
                                        <Button
                                            variant="ghost"
                                            icon="auto_fix_high"
                                            onClick={() => setResolveTarget(dup)}
                                        >
                                            Resolve
                                        </Button>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}

            {/* Nestarr — Unmatched & Nested Media */}
            <section className="mb-4">
                <h3 className="text-lg font-semibold text-primary mb-3 flex items-center flex-wrap gap-2">
                    <span className="material-symbols-outlined text-warning">account_tree</span>
                    Unmatched & Nested Media
                    {nestedIssues.length > 0 && (
                        <span className="text-sm font-normal text-warning">
                            ({nestedIssues.length} issue{nestedIssues.length !== 1 ? 's' : ''})
                        </span>
                    )}
                    <LoadingButton
                        loading={isNestScanning}
                        loadingText="Scanning..."
                        variant="ghost"
                        icon="radar"
                        onClick={handleNestedScan}
                        title="Compare ARR media against Plex and detect nested paths"
                    >
                        Scan
                    </LoadingButton>
                    {lastScanTime && (
                        <span className="text-xs font-normal text-tertiary sm:ml-auto">
                            Last scan: {new Date(lastScanTime).toLocaleString()}
                        </span>
                    )}
                </h3>
                {nestedIssues.length > 0 ? (
                    <div className="grid gap-2">
                        {nestedIssues.map(issue => {
                            const isArrNotPlex = issue.type === 'arr_not_in_plex';
                            const isPlexNotArr = issue.type === 'plex_not_in_arr';
                            const isUnmatched = isArrNotPlex || isPlexNotArr;
                            const isFilesystem = [
                                'stray_folder',
                                'stray_file',
                                'extra_video_in_folder',
                            ].includes(issue.type);
                            const isNested = !isUnmatched && !isFilesystem;

                            let badgeLabel, badgeColor, badgeBg;
                            if (isArrNotPlex) {
                                badgeLabel = 'Not in Plex';
                                badgeColor = 'text-warning';
                                badgeBg = 'bg-warning/10';
                            } else if (isPlexNotArr) {
                                badgeLabel = 'Not in ARR';
                                badgeColor = 'text-info';
                                badgeBg = 'bg-info/10';
                            } else if (issue.type === 'stray_folder') {
                                badgeLabel = 'Stray Folder';
                                badgeColor = 'text-error';
                                badgeBg = 'bg-error/10';
                            } else if (issue.type === 'stray_file') {
                                badgeLabel = 'Stray File';
                                badgeColor = 'text-error';
                                badgeBg = 'bg-error/10';
                            } else if (issue.type === 'extra_video_in_folder') {
                                badgeLabel = 'Extra Video Files';
                                badgeColor = 'text-error';
                                badgeBg = 'bg-error/10';
                            } else {
                                badgeLabel = issue.type
                                    .replace(/_/g, ' ')
                                    .replace(/\b\w/g, c => c.toUpperCase());
                                badgeColor = 'text-error';
                                badgeBg = 'bg-error/10';
                            }

                            return (
                                <div
                                    key={issue.id}
                                    className="p-3 rounded-lg bg-surface border border-border"
                                >
                                    <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2 sm:gap-3">
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center flex-wrap gap-2 mb-1">
                                                <span
                                                    className={`text-xs px-2 py-0.5 rounded-full ${badgeBg} ${badgeColor} font-medium`}
                                                >
                                                    {badgeLabel}
                                                </span>
                                                <span className="text-xs text-secondary">
                                                    {issue.instance}
                                                </span>
                                                {isPlexNotArr && issue.library_name && (
                                                    <span className="text-xs text-tertiary">
                                                        {issue.library_name}
                                                    </span>
                                                )}
                                            </div>
                                            {isUnmatched ? (
                                                <>
                                                    <div className="text-sm text-primary font-medium">
                                                        {issue.name}
                                                        {issue.year && (
                                                            <span className="text-secondary font-normal">
                                                                {' '}
                                                                ({issue.year})
                                                            </span>
                                                        )}
                                                    </div>
                                                    {issue.path && (
                                                        <div className="text-xs text-tertiary mt-1 font-mono truncate">
                                                            {issue.path}
                                                        </div>
                                                    )}
                                                </>
                                            ) : isFilesystem ? (
                                                <>
                                                    <div className="text-sm text-primary font-medium">
                                                        {issue.name}
                                                        {issue.year && (
                                                            <span className="text-secondary font-normal">
                                                                {' '}
                                                                ({issue.year})
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="text-xs text-tertiary mt-1 font-mono truncate">
                                                        {issue.path}
                                                    </div>
                                                    {issue.video_files &&
                                                        issue.video_files.length > 0 && (
                                                            <div className="text-xs text-error mt-1">
                                                                {issue.video_files.length} video
                                                                files:{' '}
                                                                {issue.video_files.join(', ')}
                                                            </div>
                                                        )}
                                                </>
                                            ) : (
                                                <>
                                                    <div className="text-sm text-secondary">
                                                        <span className="text-primary font-medium">
                                                            {issue.nested?.title}
                                                        </span>
                                                        {issue.nested?.year && (
                                                            <span> ({issue.nested.year})</span>
                                                        )}
                                                        <span className="text-tertiary">
                                                            {' '}
                                                            is nested inside{' '}
                                                        </span>
                                                        <span className="text-primary font-medium">
                                                            {issue.parent?.title}
                                                        </span>
                                                        {issue.parent?.year && (
                                                            <span> ({issue.parent.year})</span>
                                                        )}
                                                    </div>
                                                    <div className="text-xs text-tertiary mt-1 font-mono truncate">
                                                        {issue.path}
                                                    </div>
                                                </>
                                            )}
                                        </div>
                                        {isNested && (
                                            <Button
                                                variant="ghost"
                                                icon="drive_file_move"
                                                onClick={() => handlePreviewFix(issue)}
                                            >
                                                Fix
                                            </Button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    <p className="text-sm text-secondary">
                        Click Scan to compare ARR media against Plex and detect nested media paths.
                    </p>
                )}
            </section>

            {/* Collections */}
            {Array.isArray(collections) && collections.length > 0 && (
                <section className="mb-4">
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
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {collections.map((col, i) => (
                            <div
                                key={col.id || i}
                                className="p-3 rounded-lg bg-surface border border-border group flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2"
                            >
                                <div className="flex items-center gap-2 min-w-0">
                                    <span className="font-medium text-primary truncate">
                                        {col.title || col.name}
                                    </span>
                                    {col.year && (
                                        <span className="text-secondary flex-shrink-0">
                                            ({col.year})
                                        </span>
                                    )}
                                </div>
                                <div className="flex items-center gap-1">
                                    <IconButton
                                        icon="edit"
                                        aria-label="Edit collection"
                                        title="Rename this collection"
                                        variant="ghost"
                                        className="opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-fast"
                                        onClick={() => {
                                            setEditCollection(col);
                                            setEditCollectionName(col.title || col.name || '');
                                        }}
                                    />
                                    <IconButton
                                        icon="delete"
                                        aria-label="Delete collection"
                                        title="Delete this collection (media items are not deleted)"
                                        variant="ghost"
                                        className="opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-fast"
                                        onClick={() => handleDeleteCollection(col.id)}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}

            <LibraryMaintenance />

            <Modal
                isOpen={!!deleteTarget}
                onClose={() => {
                    setDeleteTarget(null);
                    setDeleteFiles(false);
                }}
                size="small"
            >
                <Modal.Header>Delete Media Item</Modal.Header>
                <Modal.Body>
                    <p className="text-secondary">
                        Are you sure you want to delete{' '}
                        <span className="font-semibold text-primary">{deleteTarget?.title}</span>?
                        This action cannot be undone.
                    </p>
                    <label className="flex items-center gap-2 mt-3 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={deleteFiles}
                            onChange={e => setDeleteFiles(e.target.checked)}
                            className="rounded border-border"
                        />
                        <span className="text-sm text-secondary">Also delete files from disk</span>
                    </label>
                    {deleteFiles && (
                        <p className="text-xs text-warning mt-1">
                            Warning: This will permanently remove the media files from your ARR
                            instance.
                        </p>
                    )}
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

            <Modal
                isOpen={!!resolveTarget}
                onClose={() => {
                    setResolveTarget(null);
                    setResolveKeepId(null);
                    setResolveDeleteFiles(false);
                }}
                size="medium"
            >
                <Modal.Header>Resolve Duplicates</Modal.Header>
                <Modal.Body>
                    <p className="text-secondary mb-3">
                        Select which copy of{' '}
                        <span className="font-semibold text-primary">
                            {resolveTarget?.title || resolveTarget?.normalized_title}
                        </span>{' '}
                        to keep. The others will be removed.
                    </p>
                    <div className="grid gap-2">
                        {(resolveTarget?.ids || '').split(',').map(idStr => {
                            const id = parseInt(idStr.trim(), 10);
                            if (isNaN(id)) return null;
                            const item = items.find(m => m.id === id);
                            const instance = (resolveTarget?.instances || '').split(',');
                            const idx = (resolveTarget?.ids || '')
                                .split(',')
                                .findIndex(s => parseInt(s.trim(), 10) === id);
                            const instanceName = instance[idx]?.trim() || 'unknown';
                            return (
                                <label
                                    key={id}
                                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                                        resolveKeepId === id
                                            ? 'border-primary bg-primary/5'
                                            : 'border-border bg-surface hover:border-secondary'
                                    }`}
                                >
                                    <input
                                        type="radio"
                                        name="keep-duplicate"
                                        checked={resolveKeepId === id}
                                        onChange={() => setResolveKeepId(id)}
                                        className="accent-primary"
                                    />
                                    <div className="flex-1 min-w-0">
                                        <div className="font-medium text-primary truncate">
                                            {item?.title || `ID: ${id}`}
                                        </div>
                                        <div className="flex items-center gap-2 text-xs text-secondary mt-0.5">
                                            <span className="px-1.5 py-0.5 rounded bg-surface-alt">
                                                {instanceName}
                                            </span>
                                            {item?.year && <span>{item.year}</span>}
                                            {item?.asset_type && (
                                                <span className="capitalize">
                                                    {item.asset_type}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    {resolveKeepId === id && (
                                        <span className="text-xs px-2 py-0.5 rounded-full bg-success/10 text-success font-medium">
                                            Keep
                                        </span>
                                    )}
                                </label>
                            );
                        })}
                    </div>
                    <label className="flex items-center gap-2 mt-3 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={resolveDeleteFiles}
                            onChange={e => setResolveDeleteFiles(e.target.checked)}
                            className="rounded border-border"
                        />
                        <span className="text-sm text-secondary">
                            Delete files from disk for removed copies
                        </span>
                    </label>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button
                        variant="ghost"
                        onClick={() => {
                            setResolveTarget(null);
                            setResolveKeepId(null);
                            setResolveDeleteFiles(false);
                        }}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        icon="auto_fix_high"
                        onClick={handleResolve}
                        disabled={isResolving || !resolveKeepId}
                    >
                        {isResolving ? 'Resolving...' : 'Resolve'}
                    </Button>
                </Modal.Footer>
            </Modal>
            <EditMediaModal
                isOpen={!!editTarget}
                onClose={() => setEditTarget(null)}
                item={editTarget}
                onSave={(id, metadata) => saveMetadata(id, metadata)}
                isSaving={isSaving}
            />
            <Modal
                isOpen={showImport}
                onClose={() => {
                    setShowImport(false);
                    setImportText('');
                }}
                size="medium"
            >
                <Modal.Header>Import Media</Modal.Header>
                <Modal.Body>
                    <p className="text-secondary mb-3">
                        Add movies or series to your Radarr/Sonarr instances. Enter one title per
                        line, or paste a JSON array.
                    </p>
                    <textarea
                        value={importText}
                        onChange={e => setImportText(e.target.value)}
                        placeholder={'The Matrix\nInception\nBreaking Bad'}
                        rows={8}
                        className="w-full p-3 bg-input border border-border rounded-md text-primary text-sm font-mono resize-y focus:border-primary focus:outline-none"
                    />
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setShowImport(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        icon="add"
                        onClick={handleImport}
                        disabled={isImporting || !importText.trim()}
                    >
                        {isImporting ? 'Importing...' : 'Import'}
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
                <Modal.Header>Create Collection</Modal.Header>
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
                        onClick={handleCreateCollection}
                        disabled={isCreatingCollection || !newCollectionName.trim()}
                    >
                        {isCreatingCollection ? 'Creating...' : 'Create'}
                    </Button>
                </Modal.Footer>
            </Modal>
            {/* Edit Collection Modal */}
            <Modal
                isOpen={!!editCollection}
                onClose={() => {
                    setEditCollection(null);
                    setEditCollectionName('');
                }}
                size="small"
            >
                <Modal.Header>Edit Collection</Modal.Header>
                <Modal.Body>
                    <label className="block text-sm text-secondary mb-1">Collection Name</label>
                    <input
                        type="text"
                        value={editCollectionName}
                        onChange={e => setEditCollectionName(e.target.value)}
                        className="w-full p-2 bg-input border border-border rounded-md text-primary text-sm focus:border-primary focus:outline-none"
                    />
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setEditCollection(null)}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        icon="save"
                        onClick={() =>
                            updateCollectionMutation(editCollection.id, {
                                name: editCollectionName.trim(),
                            })
                        }
                        disabled={isUpdatingCollection || !editCollectionName.trim()}
                    >
                        {isUpdatingCollection ? 'Saving...' : 'Save'}
                    </Button>
                </Modal.Footer>
            </Modal>
            {/* Fix Nested Media Modal — shows preview before executing */}
            <Modal
                isOpen={!!fixTarget}
                onClose={() => {
                    setFixTarget(null);
                    setFixPreview(null);
                }}
                size="medium"
            >
                <Modal.Header>Fix Nested Media</Modal.Header>
                <Modal.Body>
                    {previewLoading ? (
                        <Spinner size="medium" text="Loading preview..." center />
                    ) : fixPreview?.already_correct ? (
                        <p className="text-secondary">
                            This item is already at the correct path — no action needed.
                        </p>
                    ) : (
                        <>
                            <p className="text-secondary">
                                Move{' '}
                                <span className="font-semibold text-primary">
                                    {fixPreview?.title || fixTarget?.nested?.title}
                                </span>
                                {fixPreview?.year && ` (${fixPreview.year})`} out of{' '}
                                <span className="font-semibold text-primary">
                                    {fixTarget?.parent?.title}
                                </span>
                                &apos;s folder?
                            </p>
                            <div className="mt-3 p-2 rounded bg-surface-alt">
                                <span className="text-xs text-secondary block">Current path</span>
                                <span className="text-sm font-mono text-primary break-all">
                                    {fixPreview?.current_path || fixTarget?.nested?.path}
                                </span>
                            </div>
                            <div className="mt-2 p-2 rounded bg-surface-alt">
                                <span className="text-xs text-secondary block">Move to</span>
                                <span className="text-sm font-mono text-success break-all">
                                    {fixPreview?.target_path || fixTarget?.suggested_path}
                                </span>
                            </div>
                            {fixPreview?.rename_preview?.length > 0 && (
                                <div className="mt-3">
                                    <span className="text-xs text-secondary block mb-1">
                                        Pending file renames (from {fixTarget?.nested?.instance}{' '}
                                        naming format)
                                    </span>
                                    <div className="space-y-1 max-h-40 overflow-y-auto">
                                        {fixPreview.rename_preview.map((r, idx) => (
                                            <div
                                                key={idx}
                                                className="p-2 rounded bg-surface-alt text-xs font-mono"
                                            >
                                                <div className="text-secondary truncate">
                                                    {r.existing_path}
                                                </div>
                                                <div className="text-success truncate">
                                                    → {r.new_path}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {fixPreview && fixPreview.rename_preview?.length === 0 && (
                                <p className="text-xs text-secondary mt-2">
                                    No file renames pending — names already match the naming format.
                                </p>
                            )}
                        </>
                    )}
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button
                        variant="ghost"
                        onClick={() => {
                            setFixTarget(null);
                            setFixPreview(null);
                        }}
                    >
                        Cancel
                    </Button>
                    {!previewLoading && !fixPreview?.already_correct && (
                        <Button
                            variant="primary"
                            icon="drive_file_move"
                            onClick={handleNestedFix}
                            disabled={isNestFixing}
                        >
                            {isNestFixing ? 'Moving...' : 'Confirm Move'}
                        </Button>
                    )}
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default MediaManagePage;
