import React, { useState, useMemo, useEffect } from 'react';
import { useApiData, useApiMutation } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { mediaAPI } from '../../utils/api/media.js';
import { nestarrAPI } from '../../utils/api/nestarr.js';
import { apiCore } from '../../utils/api/core.js';
import { Modal } from '../../components/modals/Modal';
import EditMediaModal from '../../components/modals/EditMediaModal.jsx';
import { Button, LoadingButton, IconButton } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';
import { LibraryMaintenance } from '../../components/maintenance/LibraryMaintenance.jsx';
import { formatDateTime, formatDate } from '../../utils/datetime.js';

const fmtBytes = n => {
    if (!n) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let s = n;
    let i = 0;
    while (s >= 1024 && i < u.length - 1) {
        s /= 1024;
        i += 1;
    }
    return `${s.toFixed(1)} ${u[i]}`;
};

const dupKey = dup => String(dup.id ?? dup.ids ?? dup.normalized_title);
const dupIds = dup => (dup.ids || '').split(',').map(Number).filter(Boolean);

/** One duplicate group: a header that expands to the mock's per-copy grid
 *  (checkbox + quality + size + path + suggested KEEP/DUPLICATE). Copy details
 *  are loaded lazily on first expand (they need a live *arr probe per copy). */
/** Mock-styled section header: a coloured glyph, a Space-Grotesk h2, an
 *  optional mono count pill, and a right-aligned slot for filters/actions. */
const ManageSectionHeader = ({ icon, iconClass, title, count, countClass, children }) => (
    <div className="flex items-center flex-wrap gap-3 mb-3.5">
        <span className={`material-symbols-outlined text-[22px] ${iconClass}`} aria-hidden="true">
            {icon}
        </span>
        <h2 className="font-display text-xl font-bold text-fg">{title}</h2>
        {count != null && (
            <span
                className={`font-mono text-[11px] font-semibold px-2.5 py-0.5 rounded-full ${countClass}`}
            >
                {count}
            </span>
        )}
        {children}
    </div>
);

const DuplicateGroup = ({
    dup,
    expanded,
    members,
    loading,
    selected,
    onToggleExpand,
    onToggleSelect,
    onResolve,
}) => {
    const uniqueInstances = dup.instances
        ? [...new Set(dup.instances.split(','))].map(s => s.trim()).filter(Boolean)
        : [];
    // The largest file is the suggested keeper; the rest are flagged duplicates.
    const keepId =
        members && members.length
            ? members.reduce((a, b) =>
                  (b.live?.size_bytes || 0) > (a.live?.size_bytes || 0) ? b : a
              ).id
            : null;

    return (
        <section className="bg-surface border border-border rounded-xl overflow-hidden">
            <button
                type="button"
                onClick={onToggleExpand}
                className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-row-hover transition-colors"
            >
                <span
                    className="material-symbols-outlined text-[18px] text-fg-subtle transition-transform shrink-0"
                    style={{ transform: expanded ? 'rotate(90deg)' : 'none' }}
                    aria-hidden="true"
                >
                    chevron_right
                </span>
                <span className="font-display text-[15px] font-semibold text-fg truncate">
                    {dup.title || dup.normalized_title}
                </span>
                {dup.year && <span className="font-mono text-xs text-fg-subtle">{dup.year}</span>}
                <span className="font-mono text-[10px] uppercase px-[7px] py-0.5 rounded-[5px] bg-warning/15 text-warning shrink-0">
                    {dup.count} copies
                </span>
                {uniqueInstances.length > 0 && (
                    <span className="ml-auto font-mono text-[11.5px] text-fg-subtle truncate hidden sm:inline">
                        {uniqueInstances.join(' · ')}
                    </span>
                )}
            </button>

            {expanded &&
                (loading ? (
                    <div className="px-4 py-4 border-t border-border-light">
                        <Spinner size="small" text="Probing copies…" />
                    </div>
                ) : members && members.length ? (
                    <div className="border-t border-border-light">
                        {members.map(m => {
                            const id = m.id;
                            const live = m.live || {};
                            const isKeep = id === keepId;
                            const isSel = selected.has(id);
                            return (
                                <div
                                    key={id}
                                    className="grid items-center gap-3 px-4 py-3 border-b border-border-light last:border-0"
                                    style={{
                                        gridTemplateColumns: '26px 1.2fr 0.7fr 1.7fr 96px',
                                    }}
                                >
                                    <button
                                        type="button"
                                        onClick={() => onToggleSelect(id, live.size_bytes || 0)}
                                        aria-label={isSel ? 'Deselect copy' : 'Select copy'}
                                        className="w-[18px] h-[18px] rounded-[5px] flex items-center justify-center transition-colors"
                                        style={{
                                            background: isSel ? 'var(--primary)' : 'transparent',
                                            border: `1px solid ${isSel ? 'var(--primary)' : '#3b3d72'}`,
                                        }}
                                    >
                                        {isSel && (
                                            <span className="material-symbols-outlined text-white text-[13px]">
                                                check
                                            </span>
                                        )}
                                    </button>
                                    <span
                                        className={`font-mono text-[12.5px] font-semibold truncate ${
                                            isKeep ? 'text-success' : 'text-fg-muted'
                                        }`}
                                        title={live.quality || ''}
                                    >
                                        {live.quality || '—'}
                                    </span>
                                    <span className="font-mono text-[12px] text-fg-muted">
                                        {live.size_human || '—'}
                                    </span>
                                    <span
                                        className="font-mono text-[11px] text-fg-subtle truncate"
                                        title={live.path || m.folder || ''}
                                    >
                                        {live.path || m.folder || '—'}
                                    </span>
                                    <span className="text-right">
                                        <span
                                            className={`font-mono text-[10px] font-semibold px-[9px] py-[3px] rounded-full ${
                                                isKeep
                                                    ? 'bg-success/15 text-success'
                                                    : 'bg-error/15 text-error'
                                            }`}
                                        >
                                            {isKeep ? 'KEEP' : 'DUPLICATE'}
                                        </span>
                                    </span>
                                </div>
                            );
                        })}
                        <div className="flex justify-end px-4 py-2.5">
                            <Button
                                variant="ghost"
                                size="small"
                                icon="auto_fix_high"
                                onClick={() => onResolve(dup)}
                            >
                                Resolve manually
                            </Button>
                        </div>
                    </div>
                ) : (
                    <div className="px-4 py-4 border-t border-border-light text-sm text-fg-subtle">
                        Couldn&apos;t load copy details for this group.
                    </div>
                ))}
        </section>
    );
};

/** The Duplicates section: lazy-expand per-group copy grids, a cross-group
 *  selection, and a bulk-delete bar. Falls back to the per-group Resolve modal
 *  for picking a keeper manually. */
const DuplicatesSection = ({ duplicates, onResolve, onRefresh }) => {
    const toast = useToast();
    const [expanded, setExpanded] = useState({});
    const [membersByKey, setMembersByKey] = useState({});
    const [loadingKeys, setLoadingKeys] = useState(() => new Set());
    // id -> size_bytes, so the bulk bar can total the space freed.
    const [selected, setSelected] = useState({});
    // Off by default; disk deletion is opt-in and confirmed in the modal.
    const [deleteFiles, setDeleteFiles] = useState(false);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [filter, setFilter] = useState('');

    const toggleExpand = async dup => {
        const k = dupKey(dup);
        const willOpen = !expanded[k];
        setExpanded(e => ({ ...e, [k]: willOpen }));
        if (willOpen && !membersByKey[k]) {
            setLoadingKeys(s => new Set(s).add(k));
            try {
                const res = await mediaAPI.fetchDuplicateMembers(dupIds(dup));
                setMembersByKey(m => ({ ...m, [k]: res?.data?.members || [] }));
            } catch {
                setMembersByKey(m => ({ ...m, [k]: [] }));
            } finally {
                setLoadingKeys(s => {
                    const n = new Set(s);
                    n.delete(k);
                    return n;
                });
            }
        }
    };

    const toggleSelect = (id, bytes) =>
        setSelected(sel => {
            const next = { ...sel };
            if (id in next) delete next[id];
            else next[id] = bytes;
            return next;
        });

    const selectedIds = Object.keys(selected).map(Number);
    const freed = selectedIds.reduce((sum, id) => sum + (selected[id] || 0), 0);

    const doDelete = async () => {
        setConfirmOpen(false);
        setBusy(true);
        try {
            const res = await mediaAPI.bulkDeleteMedia(selectedIds, { deleteFiles });
            const removed = res?.data?.removed?.length ?? selectedIds.length;
            toast.success(`Deleted ${removed} cop${removed === 1 ? 'y' : 'ies'}`);
            setSelected({});
            setMembersByKey({});
            setExpanded({});
            onRefresh();
        } catch {
            toast.error('Bulk delete failed');
        } finally {
            setBusy(false);
        }
    };

    const q = filter.trim().toLowerCase();
    const shown = q
        ? duplicates.filter(d => (d.title || d.normalized_title || '').toLowerCase().includes(q))
        : duplicates;

    return (
        <section className="mt-6">
            <ManageSectionHeader
                icon="content_copy"
                iconClass="text-accent"
                title="Duplicate Files"
                count={`${duplicates.length} group${duplicates.length === 1 ? '' : 's'}`}
                countClass="bg-warning/15 text-warning"
            >
                {duplicates.length > 0 && (
                    <div className="ml-auto flex items-center gap-2 h-9 px-3 rounded-lg bg-surface border border-border w-full sm:w-auto sm:flex-[0_1_280px]">
                        <span
                            className="material-symbols-outlined text-base text-fg-subtle"
                            aria-hidden="true"
                        >
                            search
                        </span>
                        <input
                            type="text"
                            value={filter}
                            onChange={e => setFilter(e.target.value)}
                            placeholder="Filter duplicates…"
                            className="flex-1 min-w-0 bg-transparent border-0 outline-none text-[12.5px] text-fg placeholder:text-fg-subtle"
                        />
                    </div>
                )}
            </ManageSectionHeader>

            {duplicates.length === 0 && (
                <div className="rounded-xl bg-surface border border-border px-4 py-6 text-center text-sm text-fg-subtle">
                    No duplicate files found.
                </div>
            )}

            {selectedIds.length > 0 && (
                <div className="flex items-center gap-3.5 flex-wrap px-4 py-3 mb-4 rounded-lg bg-primary/10 border border-primary/30">
                    <span className="flex items-center justify-center w-5 h-5 rounded-[5px] bg-primary">
                        <span className="material-symbols-outlined text-white text-[14px]">
                            check
                        </span>
                    </span>
                    <span className="text-[13.5px] font-semibold text-fg">
                        {selectedIds.length} cop{selectedIds.length === 1 ? 'y' : 'ies'} selected
                    </span>
                    <span className="font-mono text-[12px] text-fg-muted">
                        frees {fmtBytes(freed)}
                    </span>
                    <div className="ml-auto flex gap-2">
                        <Button variant="ghost" size="small" onClick={() => setSelected({})}>
                            Clear
                        </Button>
                        <LoadingButton
                            loading={busy}
                            loadingText="Deleting…"
                            variant="danger"
                            size="small"
                            icon="delete"
                            onClick={() => setConfirmOpen(true)}
                        >
                            Delete copies
                        </LoadingButton>
                    </div>
                </div>
            )}

            <div className="flex flex-col gap-3.5">
                {shown.slice(0, 10).map((dup, i) => {
                    const k = dupKey(dup);
                    return (
                        <DuplicateGroup
                            key={dup.id || i}
                            dup={dup}
                            expanded={!!expanded[k]}
                            members={membersByKey[k]}
                            loading={loadingKeys.has(k)}
                            selected={new Set(selectedIds)}
                            onToggleExpand={() => toggleExpand(dup)}
                            onToggleSelect={toggleSelect}
                            onResolve={onResolve}
                        />
                    );
                })}
            </div>

            <Modal isOpen={confirmOpen} onClose={() => setConfirmOpen(false)} size="small">
                <Modal.Header>Delete Duplicate Copies</Modal.Header>
                <Modal.Body>
                    <p className="text-fg-muted">
                        Delete{' '}
                        <span className="font-semibold text-fg">
                            {selectedIds.length} cop{selectedIds.length === 1 ? 'y' : 'ies'}
                        </span>
                        ? This action cannot be undone.
                    </p>
                    <label className="flex items-center gap-2 mt-3 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={deleteFiles}
                            onChange={e => setDeleteFiles(e.target.checked)}
                            className="rounded border-border"
                        />
                        <span className="text-sm text-fg-muted">Also delete files from disk</span>
                    </label>
                    {deleteFiles && (
                        <p className="text-xs text-warning mt-1">
                            Warning: This will permanently remove the media files from your ARR
                            instance and disk.
                        </p>
                    )}
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
                        Cancel
                    </Button>
                    <LoadingButton
                        loading={busy}
                        loadingText="Deleting…"
                        variant="danger"
                        icon="delete"
                        onClick={doDelete}
                    >
                        Delete copies
                    </LoadingButton>
                </Modal.Footer>
            </Modal>
        </section>
    );
};

const MediaManagePage = () => {
    const toast = useToast();
    const [deleteTarget, setDeleteTarget] = useState(null);
    const [deleteFiles, setDeleteFiles] = useState(false);
    const [editTarget, setEditTarget] = useState(null);
    const [resolveTarget, setResolveTarget] = useState(null);
    const [resolveKeepId, setResolveKeepId] = useState(null);
    const [resolveDeleteFiles, setResolveDeleteFiles] = useState(false);
    const [resolveMembers, setResolveMembers] = useState(null);
    const [resolveMembersLoading, setResolveMembersLoading] = useState(false);
    const [showCreateCollection, setShowCreateCollection] = useState(false);
    const [newCollectionName, setNewCollectionName] = useState('');
    const [editCollection, setEditCollection] = useState(null);
    const [editCollectionName, setEditCollectionName] = useState('');
    const [nestedIssues, setNestedIssues] = useState([]);
    const [lastScanTime, setLastScanTime] = useState(null);
    const [unmatchedEnabled, setUnmatchedEnabled] = useState(true);
    const [fixTarget, setFixTarget] = useState(null);
    const [fixPreview, setFixPreview] = useState(null);
    const [previewLoading, setPreviewLoading] = useState(false);

    const { execute: saveMetadata, isLoading: isSaving } = useApiMutation(
        (id, metadata) => mediaAPI.updateMediaMetadata(id, metadata),
        {
            successMessage: 'Metadata updated',
            onSuccess: () => {
                setEditTarget(null);
            },
        }
    );

    const { data: dupData, refresh: refreshDups } = useApiData({
        apiFunction: mediaAPI.fetchDuplicates,
        options: { showErrorToast: false },
    });

    const { execute: runExport, isLoading: isExporting } = useApiMutation(() =>
        mediaAPI.exportMedia({ format: 'json' })
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
        // execute() forwards a single arg — take one object, not (id, data).
        ({ id, data }) => mediaAPI.updateCollection(id, data),
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
            setUnmatchedEnabled(result?.data?.unmatched_enabled !== false);
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
                if (data) {
                    setUnmatchedEnabled(data.unmatched_enabled !== false);
                }
            })
            .catch(() => {});
    }, []);

    // Fetch live per-member detail (size, quality, path, ...) when the
    // Resolve Duplicates modal opens. Without this the rows would only have
    // the cache snapshot — missing size / quality / file count.
    useEffect(() => {
        if (!resolveTarget) return;
        const ids = (resolveTarget.ids || '')
            .split(',')
            .map(s => parseInt(s.trim(), 10))
            .filter(n => !Number.isNaN(n));
        if (ids.length === 0) return;
        let cancelled = false;
        // eslint-disable-next-line react-hooks/set-state-in-effect -- valid loading-state pattern for async fetch
        setResolveMembersLoading(true);
        mediaAPI
            .fetchDuplicateMembers(ids)
            .then(result => {
                if (!cancelled) setResolveMembers(result?.data?.members || []);
            })
            .catch(() => {
                if (!cancelled) setResolveMembers([]);
            })
            .finally(() => {
                if (!cancelled) setResolveMembersLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [resolveTarget]);

    const { execute: runNestedFix, isLoading: isNestFixing } = useApiMutation(
        params => nestarrAPI.fix(params),
        { successMessage: 'Nested media item moved successfully' }
    );

    const duplicates = useMemo(() => dupData?.data?.duplicates || [], [dupData]);
    const folderCollisions = useMemo(() => dupData?.data?.folder_collisions || [], [dupData]);
    const collections = useMemo(
        () => collectionsData?.data?.collections || collectionsData?.data || [],
        [collectionsData]
    );

    const { execute: runRefreshCache, isLoading: isRefreshing } = useApiMutation(
        () => mediaAPI.refreshLibrary(),
        {
            successMessage: 'Cache refresh initiated',
            onSuccess: () => {
                refreshDups();
            },
        }
    );

    const handleRefreshCache = async () => {
        await runRefreshCache();
    };

    const handleExport = async () => {
        try {
            const result = await runExport();
            const items = result?.data?.data ?? [];
            const blob = new Blob([JSON.stringify(items, null, 2)], {
                type: 'application/json',
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `chub-media-${new Date().toISOString().slice(0, 10)}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            toast.success(`Exported ${items.length} media items`);
        } catch {
            toast.error('Export failed');
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
            setResolveMembers(null);
            refreshDups();
        } catch {
            toast.error('Failed to resolve duplicates');
        }
    };

    return (
        <div className="flex flex-col gap-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="font-display text-[26px] font-bold tracking-[-0.3px] text-fg m-0">
                        Manage
                    </h1>
                    <p className="text-fg-subtle text-[13.5px] mt-1 mb-0">
                        Resolve duplicates, flag issues, and batch-import to your *arr instances.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <LoadingButton
                        loading={isRefreshing}
                        loadingText="Refreshing..."
                        variant="surface"
                        icon="refresh"
                        onClick={handleRefreshCache}
                        title="Re-sync all media from your Radarr and Sonarr instances into the local cache"
                    >
                        Refresh cache
                    </LoadingButton>
                    <LoadingButton
                        loading={isExporting}
                        loadingText="Exporting..."
                        variant="surface"
                        icon="download"
                        onClick={handleExport}
                        title="Download your media library data as a JSON file"
                    >
                        Export
                    </LoadingButton>
                </div>
            </div>

            <DuplicatesSection
                duplicates={duplicates}
                onResolve={setResolveTarget}
                onRefresh={refreshDups}
            />

            {folderCollisions.length > 0 && (
                <section className="mt-9">
                    <ManageSectionHeader
                        icon="folder_copy"
                        iconClass="text-error"
                        title="Folder collisions"
                        count={`${folderCollisions.length} group${folderCollisions.length === 1 ? '' : 's'}`}
                        countClass="bg-error/15 text-error"
                    />
                    <p className="text-xs text-fg-subtle -mt-1.5 mb-3">
                        Same normalized title with missing or ambiguous external IDs — can&apos;t be
                        told apart from metadata alone. Review before resolving.
                    </p>
                    <div className="grid gap-2">
                        {folderCollisions.slice(0, 10).map((dup, i) => {
                            const uniqueInstances = dup.instances
                                ? [...new Set(dup.instances.split(','))]
                                      .map(s => s.trim())
                                      .filter(Boolean)
                                : [];
                            let folderPaths = [];
                            try {
                                folderPaths = JSON.parse(dup.folders || '[]').filter(Boolean);
                            } catch {
                                folderPaths = [];
                            }
                            let memberTitles = [];
                            try {
                                memberTitles = JSON.parse(dup.titles || '[]').filter(Boolean);
                            } catch {
                                memberTitles = [];
                            }
                            const identities = (dup.identities || '')
                                .split(',')
                                .map(s => s.trim())
                                .filter(Boolean);
                            return (
                                <div
                                    key={dup.id || i}
                                    className="p-3 rounded-lg bg-surface border border-border flex flex-col gap-2"
                                >
                                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <span className="font-medium text-fg truncate">
                                                {dup.normalized_title}
                                            </span>
                                            {dup.year && (
                                                <span className="text-fg-muted flex-shrink-0">
                                                    ({dup.year})
                                                </span>
                                            )}
                                        </div>
                                        <div className="flex items-center flex-wrap gap-2 sm:gap-3">
                                            <span className="text-sm font-medium text-fg-muted">
                                                {dup.count} similar
                                            </span>
                                            <div className="flex items-center flex-wrap gap-1">
                                                {uniqueInstances.map(inst => (
                                                    <span
                                                        key={inst}
                                                        className="text-xs px-2 py-0.5 rounded-full bg-surface-alt text-fg-muted"
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
                                    {memberTitles.length > 0 && (
                                        <div className="flex flex-col gap-0.5 text-xs text-fg-muted">
                                            {memberTitles.map((t, idx) => (
                                                <span key={`${t}-${idx}`} className="truncate">
                                                    {t}
                                                    {identities[idx] && (
                                                        <span className="text-fg-subtle ml-2">
                                                            [{identities[idx]}]
                                                        </span>
                                                    )}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                    {folderPaths.length > 0 && (
                                        <div className="flex flex-col gap-0.5 text-xs font-mono text-fg-subtle">
                                            {folderPaths.map((p, idx) => (
                                                <span
                                                    key={`${p}-${idx}`}
                                                    className="truncate"
                                                    title={p}
                                                >
                                                    {p}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}

            {/* Nestarr — Unmatched & Nested Media */}
            <section className="mt-9">
                <ManageSectionHeader
                    icon="account_tree"
                    iconClass="text-warning"
                    title="Unmatched & Nested Media"
                >
                    {nestedIssues.length > 0 && (
                        <span className="font-mono text-xs text-warning">
                            ({nestedIssues.length} issue{nestedIssues.length !== 1 ? 's' : ''})
                        </span>
                    )}
                    <LoadingButton
                        loading={isNestScanning}
                        loadingText="Scanning..."
                        variant="surface"
                        size="small"
                        icon="radar"
                        onClick={handleNestedScan}
                        title="Compare ARR media against Plex and detect nested paths"
                    >
                        Scan
                    </LoadingButton>
                    {lastScanTime && (
                        <span className="ml-auto font-mono text-[11.5px] text-fg-subtle">
                            Last scan: {formatDateTime(lastScanTime)}
                        </span>
                    )}
                </ManageSectionHeader>
                {!unmatchedEnabled && (
                    <div className="mb-3 p-3 rounded-lg bg-info/10 border border-info/20 text-sm text-fg-muted">
                        <span className="material-symbols-outlined text-info align-middle mr-1 text-base">
                            info
                        </span>
                        Unmatched ARR ↔ Plex detection is off. Add{' '}
                        <a className="text-brand-primary hover:underline" href="/settings/modules">
                            library mappings in Nestarr settings
                        </a>{' '}
                        to enable it. Nested and stray-file detection still run.
                    </div>
                )}
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
                            const isNested =
                                !isUnmatched &&
                                !isFilesystem &&
                                issue.suggested_action === 'move' &&
                                Boolean(issue.suggested_path);

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
                            } else if (isNested) {
                                badgeLabel = 'Nested Folder';
                                badgeColor = 'text-warning';
                                badgeBg = 'bg-warning/10';
                            } else {
                                badgeLabel = issue.type
                                    .replace(/_/g, ' ')
                                    .replace(/\b\w/g, c => c.toUpperCase());
                                badgeColor = 'text-error';
                                badgeBg = 'bg-error/10';
                            }

                            return (
                                <section
                                    key={issue.id}
                                    className="rounded-xl bg-surface border border-border p-[15px] transition-colors hover:border-border-light"
                                >
                                    <div className="flex items-center flex-wrap gap-2.5 mb-2.5">
                                        <span
                                            className={`font-mono text-[10px] font-semibold px-2.5 py-[3px] rounded-md ${badgeBg} ${badgeColor}`}
                                        >
                                            {badgeLabel}
                                        </span>
                                        <span className="font-mono text-[11.5px] text-fg-subtle">
                                            {issue.instance}
                                        </span>
                                        {isPlexNotArr && issue.library_name && (
                                            <span className="font-mono text-[11.5px] text-fg-subtle">
                                                {issue.library_name}
                                            </span>
                                        )}
                                        {isNested && (
                                            <div className="ml-auto flex gap-1.5">
                                                <Button
                                                    variant="surface"
                                                    size="small"
                                                    icon="drive_file_move"
                                                    onClick={() => handlePreviewFix(issue)}
                                                >
                                                    Fix
                                                </Button>
                                            </div>
                                        )}
                                    </div>
                                    {isUnmatched ? (
                                        <>
                                            <div className="flex items-baseline gap-2">
                                                <span className="font-display text-base font-semibold text-fg">
                                                    {issue.name}
                                                </span>
                                                {issue.year && (
                                                    <span className="font-mono text-[13px] text-fg-subtle">
                                                        {issue.year}
                                                    </span>
                                                )}
                                            </div>
                                            {issue.path && (
                                                <div
                                                    className="mt-1 font-mono text-xs text-fg-subtle break-all"
                                                    title={issue.path}
                                                >
                                                    {issue.path}
                                                </div>
                                            )}
                                        </>
                                    ) : isFilesystem ? (
                                        <>
                                            <div className="flex items-baseline gap-2">
                                                <span className="font-display text-base font-semibold text-fg">
                                                    {issue.name}
                                                </span>
                                                {issue.year && (
                                                    <span className="font-mono text-[13px] text-fg-subtle">
                                                        {issue.year}
                                                    </span>
                                                )}
                                            </div>
                                            <div
                                                className="mt-1 font-mono text-xs text-fg-subtle break-all"
                                                title={issue.path}
                                            >
                                                {issue.path}
                                            </div>
                                            {issue.video_files && issue.video_files.length > 0 && (
                                                <div className="mt-1.5 font-mono text-xs leading-relaxed text-error/80 break-words">
                                                    {issue.video_files.length} video files:{' '}
                                                    {issue.video_files.join(' · ')}
                                                </div>
                                            )}
                                        </>
                                    ) : (
                                        <>
                                            <div className="flex items-baseline gap-2">
                                                <span className="font-display text-base font-semibold text-fg">
                                                    {issue.nested?.title}
                                                </span>
                                                {issue.nested?.year && (
                                                    <span className="font-mono text-[13px] text-fg-subtle">
                                                        {issue.nested.year}
                                                    </span>
                                                )}
                                            </div>
                                            <div className="mt-1 font-mono text-xs text-fg-subtle break-all">
                                                {issue.path}
                                            </div>
                                            <div className="mt-1.5 font-mono text-xs leading-relaxed text-warning/80 break-words">
                                                Nested inside {issue.parent?.title}
                                                {issue.parent?.year
                                                    ? ` (${issue.parent.year})`
                                                    : ''}{' '}
                                                — flatten so the *arr can detect it.
                                            </div>
                                        </>
                                    )}
                                </section>
                            );
                        })}
                    </div>
                ) : (
                    <p className="text-sm text-fg-muted">
                        Click Scan to compare ARR media against Plex and detect nested media paths.
                    </p>
                )}
            </section>

            {/* Collections */}
            {Array.isArray(collections) && collections.length > 0 && (
                <section className="mt-9">
                    <ManageSectionHeader
                        icon="collections_bookmark"
                        iconClass="text-primary"
                        title="Collections"
                        count={`${collections.length}`}
                        countClass="bg-primary/15 text-primary"
                    >
                        <Button
                            variant="ghost"
                            icon="add"
                            onClick={() => setShowCreateCollection(true)}
                        >
                            Create
                        </Button>
                    </ManageSectionHeader>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {collections.map((col, i) => (
                            <div
                                key={col.id || i}
                                className="p-3 rounded-lg bg-surface border border-border group flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2"
                            >
                                <div className="flex items-center gap-2 min-w-0">
                                    <span className="font-medium text-fg truncate">
                                        {col.title || col.name}
                                    </span>
                                    {col.year && (
                                        <span className="text-fg-muted flex-shrink-0">
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
                    <p className="text-fg-muted">
                        Are you sure you want to delete{' '}
                        <span className="font-semibold text-fg">{deleteTarget?.title}</span>? This
                        action cannot be undone.
                    </p>
                    <label className="flex items-center gap-2 mt-3 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={deleteFiles}
                            onChange={e => setDeleteFiles(e.target.checked)}
                            className="rounded border-border"
                        />
                        <span className="text-sm text-fg-muted">Also delete files from disk</span>
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
                    setResolveMembers(null);
                }}
                size="medium"
            >
                <Modal.Header>Resolve Duplicates</Modal.Header>
                <Modal.Body>
                    <p className="text-fg-muted mb-3">
                        Select which copy of{' '}
                        <span className="font-semibold text-fg">
                            {resolveTarget?.title || resolveTarget?.normalized_title}
                        </span>{' '}
                        to keep. The others will be removed.
                    </p>
                    {resolveMembersLoading && (
                        <Spinner size="medium" text="Fetching live details..." center />
                    )}
                    {!resolveMembersLoading && resolveMembers && (
                        <div className="grid gap-2">
                            {resolveMembers.map(m => {
                                const id = m.id;
                                const live = m.live || {};
                                const displayTitle = live.title || m.title || `ID: ${id}`;
                                const path = live.path || m.folder;
                                return (
                                    <label
                                        key={id}
                                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
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
                                            className="accent-primary mt-1"
                                        />
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center flex-wrap gap-2">
                                                <span className="font-medium text-fg truncate">
                                                    {displayTitle}
                                                </span>
                                                {live.monitored === false && (
                                                    <span className="text-xs px-1.5 py-0.5 rounded bg-warning/10 text-warning">
                                                        unmonitored
                                                    </span>
                                                )}
                                                {m.error && (
                                                    <span className="text-xs px-1.5 py-0.5 rounded bg-error/10 text-error">
                                                        {m.error}
                                                    </span>
                                                )}
                                            </div>
                                            <div className="flex items-center flex-wrap gap-2 text-xs text-fg-muted mt-1">
                                                <span className="px-1.5 py-0.5 rounded bg-surface-alt">
                                                    {m.instance_name || 'unknown'}
                                                </span>
                                                <span className="capitalize">{m.asset_type}</span>
                                                {m.year && <span>{m.year}</span>}
                                                <span className="font-mono text-fg-subtle">
                                                    arr_id {m.arr_id ?? '—'}
                                                </span>
                                                {live.size_human && (
                                                    <span className="font-medium text-fg">
                                                        {live.size_human}
                                                    </span>
                                                )}
                                                {live.quality && (
                                                    <span className="px-1.5 py-0.5 rounded bg-surface-alt">
                                                        {live.quality}
                                                    </span>
                                                )}
                                                {live.file_count != null && (
                                                    <span>
                                                        {live.file_count}
                                                        {live.total_count != null &&
                                                            ` / ${live.total_count}`}{' '}
                                                        file{live.file_count === 1 ? '' : 's'}
                                                    </span>
                                                )}
                                                {live.status && (
                                                    <span className="capitalize">
                                                        {live.status}
                                                    </span>
                                                )}
                                                {live.added && (
                                                    <span
                                                        className="text-fg-subtle"
                                                        title={live.added}
                                                    >
                                                        added {formatDate(live.added)}
                                                    </span>
                                                )}
                                            </div>
                                            {path && (
                                                <div
                                                    className="text-xs font-mono text-fg-subtle mt-1 truncate"
                                                    title={path}
                                                >
                                                    {path}
                                                </div>
                                            )}
                                        </div>
                                        {resolveKeepId === id && (
                                            <span className="text-xs px-2 py-0.5 rounded-full bg-success/10 text-success font-medium shrink-0 mt-1">
                                                Keep
                                            </span>
                                        )}
                                    </label>
                                );
                            })}
                        </div>
                    )}
                    <label className="flex items-center gap-2 mt-3 cursor-pointer">
                        <input
                            type="checkbox"
                            checked={resolveDeleteFiles}
                            onChange={e => setResolveDeleteFiles(e.target.checked)}
                            className="rounded border-border"
                        />
                        <span className="text-sm text-fg-muted">
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
                            setResolveMembers(null);
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
                    <label className="block text-sm text-fg-muted mb-1">Collection Name</label>
                    <input
                        type="text"
                        value={newCollectionName}
                        onChange={e => setNewCollectionName(e.target.value)}
                        placeholder="My Collection"
                        className="w-full p-2 bg-input border border-border rounded-md text-fg text-sm focus:border-primary focus:outline-none"
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
                    <label className="block text-sm text-fg-muted mb-1">Collection Name</label>
                    <input
                        type="text"
                        value={editCollectionName}
                        onChange={e => setEditCollectionName(e.target.value)}
                        className="w-full p-2 bg-input border border-border rounded-md text-fg text-sm focus:border-primary focus:outline-none"
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
                            updateCollectionMutation({
                                id: editCollection.id,
                                data: { name: editCollectionName.trim() },
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
                        <p className="text-fg-muted">
                            This item is already at the correct path — no action needed.
                        </p>
                    ) : (
                        <>
                            <p className="text-fg-muted">
                                Move{' '}
                                <span className="font-semibold text-fg">
                                    {fixPreview?.title || fixTarget?.nested?.title}
                                </span>
                                {fixPreview?.year && ` (${fixPreview.year})`} out of{' '}
                                <span className="font-semibold text-fg">
                                    {fixTarget?.parent?.title}
                                </span>
                                &apos;s folder?
                            </p>
                            <div className="mt-3 p-2 rounded bg-surface-alt">
                                <span className="text-xs text-fg-muted block">Current path</span>
                                <span className="text-sm font-mono text-fg break-all">
                                    {fixPreview?.current_path || fixTarget?.nested?.path}
                                </span>
                            </div>
                            <div className="mt-2 p-2 rounded bg-surface-alt">
                                <span className="text-xs text-fg-muted block">Move to</span>
                                <span className="text-sm font-mono text-success break-all">
                                    {fixPreview?.target_path || fixTarget?.suggested_path}
                                </span>
                            </div>
                            {fixPreview?.rename_preview?.length > 0 && (
                                <div className="mt-3">
                                    <span className="text-xs text-fg-muted block mb-1">
                                        Pending file renames (from {fixTarget?.nested?.instance}{' '}
                                        naming format)
                                    </span>
                                    <div className="space-y-1 max-h-40 overflow-y-auto">
                                        {fixPreview.rename_preview.map((r, idx) => (
                                            <div
                                                key={idx}
                                                className="p-2 rounded bg-surface-alt text-xs font-mono"
                                            >
                                                <div className="text-fg-muted truncate">
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
                                <p className="text-xs text-fg-muted mt-2">
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
