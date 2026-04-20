import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { Modal } from '../../components/modals/Modal';
import { Button, LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const PAGE_SIZE = 30;

const MODE_LABELS = {
    report: 'Report',
    move: 'Move to trash',
    remove: 'Delete permanently',
};

function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let n = bytes;
    let i = 0;
    while (n >= 1024 && i < u.length - 1) {
        n /= 1024;
        i += 1;
    }
    return `${n.toFixed(1)} ${u[i]}`;
}

/** Single poster variant tile — shows active/bloat border and selection checkbox. */
const VARIANT_KIND_LABELS = {
    poster: 'Poster',
    art: 'Art',
    banner: 'Banner',
    thumb: 'Thumb',
    chapter: 'Chapter',
    theme: 'Theme',
    other: 'Other',
};

const formatRelativeTime = mtime => {
    if (!mtime) return '';
    const ms = Date.now() - mtime * 1000;
    if (ms < 0) return '';
    const days = Math.floor(ms / 86_400_000);
    if (days < 1) return 'today';
    if (days < 30) return `${days}d ago`;
    const months = Math.floor(days / 30);
    if (months < 12) return `${months}mo ago`;
    return `${Math.floor(days / 365)}y ago`;
};

const VariantTile = ({ variant, selected, onToggleSelect, onPreview, canSelect = true }) => {
    const border = variant.active
        ? 'border-success ring-2 ring-success/50'
        : 'border-error/70 ring-1 ring-error/30';
    const kindLabel = VARIANT_KIND_LABELS[variant.kind] || null;
    const ageLabel = formatRelativeTime(variant.mtime);
    return (
        <div
            className={`relative rounded-md overflow-hidden border-2 ${border} bg-surface cursor-pointer group`}
            onClick={() => onPreview(variant)}
            title={[
                variant.active ? 'Active poster in Plex' : 'Unused (bloat) — candidate for cleanup',
                kindLabel,
                ageLabel && `modified ${ageLabel}`,
            ]
                .filter(Boolean)
                .join(' · ')}
        >
            <img
                src={postersAPI.getPlexVariantUrl(variant.path)}
                alt={variant.filename}
                loading="lazy"
                className="w-full h-40 object-cover"
            />
            {canSelect && !variant.active && (
                <label
                    className="absolute top-1 left-1 bg-black/70 rounded px-1 py-0.5 cursor-pointer"
                    onClick={e => e.stopPropagation()}
                >
                    <input
                        type="checkbox"
                        checked={selected}
                        onChange={() => onToggleSelect(variant)}
                        className="cursor-pointer"
                    />
                </label>
            )}
            {kindLabel && (
                <span
                    className={`absolute top-1 right-1 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded ${variant.active ? 'bg-success/80 text-white' : 'bg-black/70 text-white'}`}
                >
                    {kindLabel}
                </span>
            )}
            <div className="absolute bottom-0 left-0 right-0 bg-black/70 text-white text-xs px-2 py-1 flex items-center justify-between gap-2">
                <span>{formatBytes(variant.size)}</span>
                {ageLabel && <span className="text-white/70">{ageLabel}</span>}
            </div>
        </div>
    );
};

const MEDIA_TYPE_BADGE_COLOR = {
    movie: 'bg-blue-500/20 text-blue-300',
    show: 'bg-purple-500/20 text-purple-300',
    season: 'bg-indigo-500/20 text-indigo-300',
    episode: 'bg-amber-500/20 text-amber-300',
    collection: 'bg-emerald-500/20 text-emerald-300',
    artist: 'bg-pink-500/20 text-pink-300',
    album: 'bg-fuchsia-500/20 text-fuchsia-300',
};

/** One media-item bundle: title + grid of its variants. */
const BundleCard = ({ bundle, selectedPaths, onToggleSelect, onToggleBundle, onPreview }) => {
    const bloatCount = bundle.variants.filter(v => !v.active).length;
    const selectedInBundle = bundle.variants.filter(
        v => !v.active && selectedPaths.has(v.path)
    ).length;
    const allSelected = bloatCount > 0 && selectedInBundle === bloatCount;

    const titleDisplay = bundle.title
        ? `${bundle.title}${bundle.year ? ` (${bundle.year})` : ''}`
        : bundle.bundle_path.split('/').slice(-2).join('/');

    const typeLabel = bundle.metadata_type_label;
    const typeBadgeClass = MEDIA_TYPE_BADGE_COLOR[typeLabel] || 'bg-surface text-secondary';

    return (
        <section className="rounded-lg border border-border bg-surface-alt p-3 flex flex-col gap-2">
            <header className="flex items-center justify-between gap-3">
                <div className="flex-1 min-w-0">
                    <h3
                        className="text-sm font-semibold text-primary truncate flex items-center gap-2"
                        title={titleDisplay}
                    >
                        <span className="truncate">{titleDisplay}</span>
                        {typeLabel && (
                            <span
                                className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded ${typeBadgeClass}`}
                            >
                                {typeLabel}
                            </span>
                        )}
                    </h3>
                    <p className="text-xs text-secondary">
                        {bundle.library_name && (
                            <span className="text-tertiary">{bundle.library_name} · </span>
                        )}
                        {bundle.variants.length} variant{bundle.variants.length !== 1 ? 's' : ''}
                        {bloatCount > 0 && ` · ${bloatCount} bloat`}
                    </p>
                </div>
                {bloatCount > 0 && (
                    <label className="flex items-center gap-1 text-xs text-secondary cursor-pointer">
                        <input
                            type="checkbox"
                            checked={allSelected}
                            onChange={() => onToggleBundle(bundle, !allSelected)}
                        />
                        Select bloat
                    </label>
                )}
            </header>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
                {bundle.variants.map(v => (
                    <VariantTile
                        key={v.path}
                        variant={v}
                        selected={selectedPaths.has(v.path)}
                        onToggleSelect={onToggleSelect}
                        onPreview={p => onPreview(p, bundle)}
                    />
                ))}
            </div>
        </section>
    );
};

// Module-level so reference is stable across renders (fixes exhaustive-deps warning).
const TERMINAL_STATUSES = ['success', 'error', 'cancelled'];

/** Modal shown while a cleanup job runs — polls log-tail every 1.5s. */
const LiveLogModal = ({ jobId, onClose }) => {
    const [text, setText] = useState('');
    const [status, setStatus] = useState('running');
    const offsetRef = useRef(0);
    const preRef = useRef(null);

    // Reset text/status when jobId changes (render-time, not in an effect).
    const [prevJobId, setPrevJobId] = useState(jobId);
    if (prevJobId !== jobId) {
        setPrevJobId(jobId);
        setText('');
        setStatus('running');
    }

    useEffect(() => {
        if (!jobId) return undefined;
        let cancelled = false;
        let timer = null;
        // Reset log offset at the start of each new poll lifecycle.
        offsetRef.current = 0;

        const poll = () =>
            postersAPI
                .tailJobLog(jobId, offsetRef.current)
                .then(res => {
                    if (cancelled) return;
                    const data = res?.data || {};
                    if (data.lines) {
                        setText(prev => prev + data.lines);
                        offsetRef.current = data.next_offset ?? offsetRef.current;
                        // Auto-scroll to bottom
                        setTimeout(() => {
                            if (preRef.current) {
                                preRef.current.scrollTop = preRef.current.scrollHeight;
                            }
                        }, 0);
                    }
                    if (data.status) setStatus(data.status);
                    if (TERMINAL_STATUSES.includes(data.status)) return; // stop polling
                    timer = setTimeout(poll, 1500);
                })
                .catch(() => {
                    if (!cancelled) timer = setTimeout(poll, 3000);
                });
        poll();
        return () => {
            cancelled = true;
            if (timer) clearTimeout(timer);
        };
    }, [jobId]);

    const terminal = TERMINAL_STATUSES.includes(status);

    return (
        <Modal isOpen={!!jobId} onClose={onClose} size="large">
            <Modal.Header>Cleanup job #{jobId}</Modal.Header>
            <Modal.Body>
                <div className="flex flex-col gap-3">
                    <div className="text-sm text-secondary">
                        Status: <span className="font-medium text-primary">{status}</span>
                    </div>
                    <pre
                        ref={preRef}
                        className="text-xs font-mono bg-black/60 text-white p-3 rounded h-96 overflow-auto whitespace-pre-wrap"
                    >
                        {text || (terminal ? '(no output captured)' : 'Waiting for output…')}
                    </pre>
                </div>
            </Modal.Body>
            <Modal.Footer align="right">
                <Button variant="secondary" onClick={onClose}>
                    {terminal ? 'Close' : 'Hide (job keeps running)'}
                </Button>
            </Modal.Footer>
        </Modal>
    );
};

/** Preview + per-variant actions modal. */
const VariantPreviewModal = ({ target, onClose, onDelete, onSetActive }) => {
    if (!target) return null;
    const { variant, bundle } = target;
    const isActive = variant.active;
    return (
        <Modal isOpen={!!target} onClose={onClose} size="large">
            <Modal.Header>{bundle?.title || variant.filename}</Modal.Header>
            <Modal.Body>
                <div className="flex flex-col gap-3">
                    <img
                        src={postersAPI.getPlexVariantUrl(variant.path)}
                        alt={variant.filename}
                        className="max-h-[60vh] w-auto mx-auto rounded"
                    />
                    <div className="text-xs text-secondary font-mono break-all">{variant.path}</div>
                    <div className="text-sm">
                        {formatBytes(variant.size)} ·{' '}
                        {isActive ? (
                            <span className="text-success">Active</span>
                        ) : (
                            <span className="text-error">Bloat</span>
                        )}
                    </div>
                </div>
            </Modal.Body>
            <Modal.Footer align="right">
                {!isActive && bundle?.rating_key && (
                    <Button variant="primary" onClick={() => onSetActive(variant, bundle)}>
                        Make active in Plex
                    </Button>
                )}
                {!isActive && (
                    <Button variant="danger" onClick={() => onDelete(variant)}>
                        Delete this variant
                    </Button>
                )}
                <Button variant="secondary" onClick={onClose}>
                    Close
                </Button>
            </Modal.Footer>
        </Modal>
    );
};

const PosterCleanarrPage = () => {
    const toast = useToast();

    // View: by-media (grouped) | bloat (flat)
    const [view, setView] = useState('by-media');
    const [onlyBloat, setOnlyBloat] = useState(false);
    const [page, setPage] = useState(0);
    const [selectedPaths, setSelectedPaths] = useState(new Set());
    const [previewTarget, setPreviewTarget] = useState(null);
    const [confirmSetActive, setConfirmSetActive] = useState(null);
    const [liveJobId, setLiveJobId] = useState(null);
    const [isEnqueuing, setIsEnqueuing] = useState(false);
    // Plex metadata scans are expensive (walks every .bundle dir), so the
    // page stays idle until the user explicitly hits Refresh.
    const [hasScanned, setHasScanned] = useState(false);

    // Mode + Plex-maintenance toggles
    const [mode, setMode] = useState('report');
    const [emptyTrash, setEmptyTrash] = useState(false);
    const [cleanBundles, setCleanBundles] = useState(false);
    const [optimizeDb, setOptimizeDb] = useState(false);

    // ImageMaid-style filters
    const [mediaType, setMediaType] = useState('all'); // all | movie | show | season | episode | collection
    const [libraryId, setLibraryId] = useState(0); // 0 = all
    const [variantKind, setVariantKind] = useState('all'); // all | poster | art | banner | thumb | chapter | theme | other

    const byMediaParams = useMemo(
        () => ({
            limit: PAGE_SIZE,
            offset: page * PAGE_SIZE,
            only_bloat: onlyBloat,
            media_type: mediaType,
            library_id: libraryId,
            variant_kind: variantKind,
        }),
        [page, onlyBloat, mediaType, libraryId, variantKind]
    );

    const bloatParams = useMemo(() => ({ limit: PAGE_SIZE, offset: page * PAGE_SIZE }), [page]);

    // Scans don't auto-fire on mount — they walk the entire Plex metadata
    // directory. The user triggers them by clicking Refresh (which calls
    // hasScanned=true) or by switching views after the first scan.
    const byMedia = useApiData({
        apiFunction: useCallback(
            () =>
                view === 'by-media' && hasScanned
                    ? postersAPI.listPlexMetadataByMedia(byMediaParams)
                    : Promise.resolve({ data: { bundles: [], total: 0, stats: null } }),
            [byMediaParams, view, hasScanned]
        ),
        dependencies: [byMediaParams, view, hasScanned],
        options: { showErrorToast: false, immediate: false },
    });

    const bloatFlat = useApiData({
        apiFunction: useCallback(
            () =>
                view === 'bloat' && hasScanned
                    ? postersAPI.listPlexMetadataBloat(bloatParams)
                    : Promise.resolve({ data: { items: [], total: 0, stats: null } }),
            [bloatParams, view, hasScanned]
        ),
        dependencies: [bloatParams, view, hasScanned],
        options: { showErrorToast: false, immediate: false },
    });

    const bundles = useMemo(() => byMedia.data?.data?.bundles || [], [byMedia.data]);
    const libraries = useMemo(() => byMedia.data?.data?.libraries || [], [byMedia.data]);
    const bloatItems = useMemo(() => bloatFlat.data?.data?.items || [], [bloatFlat.data]);
    const stats = useMemo(
        () => (view === 'by-media' ? byMedia.data?.data?.stats : bloatFlat.data?.data?.stats),
        [view, byMedia.data, bloatFlat.data]
    );
    const total = useMemo(
        () =>
            view === 'by-media' ? byMedia.data?.data?.total || 0 : bloatFlat.data?.data?.total || 0,
        [view, byMedia.data, bloatFlat.data]
    );
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const loading = view === 'by-media' ? byMedia.isLoading : bloatFlat.isLoading;

    const refreshView = useCallback(() => {
        // First click flips the opt-in flag, which drives the useApiData
        // dep array and fires the scan via its normal path.
        if (!hasScanned) {
            setHasScanned(true);
            return;
        }
        if (view === 'by-media') byMedia.refresh();
        else bloatFlat.refresh();
    }, [view, byMedia, bloatFlat, hasScanned]);

    const toggleSelect = useCallback(variant => {
        setSelectedPaths(prev => {
            const next = new Set(prev);
            if (next.has(variant.path)) next.delete(variant.path);
            else next.add(variant.path);
            return next;
        });
    }, []);

    const toggleBundle = useCallback((bundle, select) => {
        setSelectedPaths(prev => {
            const next = new Set(prev);
            for (const v of bundle.variants) {
                if (v.active) continue;
                if (select) next.add(v.path);
                else next.delete(v.path);
            }
            return next;
        });
    }, []);

    const selectAllVisible = () => {
        const next = new Set(selectedPaths);
        if (view === 'by-media') {
            for (const b of bundles) {
                for (const v of b.variants) if (!v.active) next.add(v.path);
            }
        } else {
            for (const it of bloatItems) next.add(it.path);
        }
        setSelectedPaths(next);
    };

    const clearSelection = () => setSelectedPaths(new Set());

    const runCleanup = async () => {
        setIsEnqueuing(true);
        try {
            const body = {
                mode,
                empty_trash: emptyTrash,
                clean_bundles: cleanBundles,
                optimize_db: optimizeDb,
            };
            if (selectedPaths.size > 0) {
                body.target_paths = Array.from(selectedPaths);
            }
            const res = await postersAPI.runPlexMetadataCleanup(body);
            const jobId = res?.data?.job_id;
            if (!jobId) {
                toast.error('Failed to start cleanup');
                return;
            }
            toast.success(`Cleanup started (job #${jobId})`);
            setLiveJobId(jobId);
            setSelectedPaths(new Set());
        } catch {
            toast.error('Failed to start cleanup');
        } finally {
            setIsEnqueuing(false);
        }
    };

    const handleDeleteVariant = async variant => {
        try {
            await postersAPI.deletePlexMetadataVariant(variant.path);
            toast.success('Variant deleted');
            setPreviewTarget(null);
            refreshView();
        } catch {
            toast.error('Failed to delete variant');
        }
    };

    const handleSetActive = async () => {
        if (!confirmSetActive) return;
        const { variant, bundle } = confirmSetActive;
        try {
            await postersAPI.setPlexMetadataActive(bundle.rating_key, variant.path);
            toast.success('Active poster updated in Plex');
            setConfirmSetActive(null);
            setPreviewTarget(null);
            refreshView();
        } catch {
            toast.error('Failed to update active poster');
        }
    };

    return (
        <div className="flex flex-col gap-6">
            <PageHeader
                title="Poster Cleanarr"
                description="Review Plex poster variants and clean up unused (bloat) images."
                badge={3}
                icon="cleaning_services"
                actions={
                    stats ? (
                        <div className="text-xs text-secondary">
                            {stats.bundle_count} items · {stats.variant_count} variants ·{' '}
                            <span className="text-error">{stats.bloat_count} bloat</span> ·{' '}
                            {formatBytes(stats.bloat_size)} reclaimable
                        </div>
                    ) : null
                }
            />

            {/* Action bar */}
            <section className="rounded-lg border border-border bg-surface p-3 flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-3">
                    {/* View toggle */}
                    <div className="flex items-center gap-1 border border-border rounded-md p-1">
                        <button
                            type="button"
                            onClick={() => {
                                setView('by-media');
                                setPage(0);
                            }}
                            className={`px-3 py-1 text-sm rounded ${
                                view === 'by-media'
                                    ? 'bg-primary/15 text-primary'
                                    : 'text-secondary'
                            }`}
                        >
                            By media item
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setView('bloat');
                                setPage(0);
                            }}
                            className={`px-3 py-1 text-sm rounded ${
                                view === 'bloat' ? 'bg-primary/15 text-primary' : 'text-secondary'
                            }`}
                        >
                            Bloat only
                        </button>
                    </div>

                    {view === 'by-media' && (
                        <label className="flex items-center gap-2 text-sm">
                            <input
                                type="checkbox"
                                checked={onlyBloat}
                                onChange={e => {
                                    setOnlyBloat(e.target.checked);
                                    setPage(0);
                                }}
                            />
                            Hide items with no bloat
                        </label>
                    )}

                    <div className="ml-auto flex items-center gap-2">
                        <Button variant="ghost" onClick={refreshView} disabled={loading}>
                            <span className="material-symbols-outlined text-base">refresh</span>
                            Refresh
                        </Button>
                    </div>
                </div>

                {/* Filters — library / media type / variant kind. The scan
                    always fetches everything; these narrow the server-side
                    response so the page doesn't get overwhelmed by episode
                    thumbnails when you care about movie/show posters. */}
                {view === 'by-media' && hasScanned && (
                    <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3 text-sm">
                        <label className="flex items-center gap-2">
                            <span className="text-tertiary">Library:</span>
                            <select
                                value={libraryId}
                                onChange={e => {
                                    setLibraryId(Number(e.target.value));
                                    setPage(0);
                                }}
                                className="px-2 py-1 rounded bg-surface-alt border border-border"
                            >
                                <option value={0}>All libraries</option>
                                {libraries.map(lib => (
                                    <option key={lib.id} value={lib.id}>
                                        {lib.name}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="flex items-center gap-2">
                            <span className="text-tertiary">Type:</span>
                            <select
                                value={mediaType}
                                onChange={e => {
                                    setMediaType(e.target.value);
                                    setPage(0);
                                }}
                                className="px-2 py-1 rounded bg-surface-alt border border-border"
                            >
                                <option value="all">All</option>
                                <option value="movie">Movie</option>
                                <option value="show">Show</option>
                                <option value="season">Season</option>
                                <option value="episode">Episode</option>
                                <option value="collection">Collection</option>
                                <option value="artist">Artist</option>
                                <option value="album">Album</option>
                            </select>
                        </label>
                        <label className="flex items-center gap-2">
                            <span className="text-tertiary">Kind:</span>
                            <select
                                value={variantKind}
                                onChange={e => {
                                    setVariantKind(e.target.value);
                                    setPage(0);
                                }}
                                className="px-2 py-1 rounded bg-surface-alt border border-border"
                            >
                                <option value="all">All</option>
                                <option value="poster">Posters</option>
                                <option value="art">Background art</option>
                                <option value="banner">Banners</option>
                                <option value="thumb">Thumbnails</option>
                                <option value="chapter">Chapter images</option>
                                <option value="theme">Themes</option>
                                <option value="other">Other</option>
                            </select>
                        </label>
                        {(mediaType !== 'all' || libraryId !== 0 || variantKind !== 'all') && (
                            <button
                                type="button"
                                onClick={() => {
                                    setMediaType('all');
                                    setLibraryId(0);
                                    setVariantKind('all');
                                    setPage(0);
                                }}
                                className="text-xs text-accent hover:underline bg-transparent border-0 cursor-pointer"
                            >
                                Clear filters
                            </button>
                        )}
                    </div>
                )}

                <div className="flex flex-wrap items-center gap-3 border-t border-border pt-3">
                    <label className="flex items-center gap-2 text-sm">
                        Mode:
                        <select
                            value={mode}
                            onChange={e => setMode(e.target.value)}
                            className="bg-surface-alt border border-border rounded px-2 py-1 text-sm"
                        >
                            {Object.entries(MODE_LABELS).map(([k, v]) => (
                                <option key={k} value={k}>
                                    {v}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="flex items-center gap-1 text-sm">
                        <input
                            type="checkbox"
                            checked={emptyTrash}
                            onChange={e => setEmptyTrash(e.target.checked)}
                        />
                        Empty trash
                    </label>
                    <label className="flex items-center gap-1 text-sm">
                        <input
                            type="checkbox"
                            checked={cleanBundles}
                            onChange={e => setCleanBundles(e.target.checked)}
                        />
                        Clean bundles
                    </label>
                    <label className="flex items-center gap-1 text-sm">
                        <input
                            type="checkbox"
                            checked={optimizeDb}
                            onChange={e => setOptimizeDb(e.target.checked)}
                        />
                        Optimize DB
                    </label>

                    <div className="ml-auto flex items-center gap-2">
                        <span className="text-xs text-secondary">
                            {selectedPaths.size > 0
                                ? `${selectedPaths.size} selected`
                                : 'No selection → full library'}
                        </span>
                        <Button variant="ghost" onClick={selectAllVisible} disabled={loading}>
                            Select visible bloat
                        </Button>
                        {selectedPaths.size > 0 && (
                            <Button variant="ghost" onClick={clearSelection}>
                                Clear
                            </Button>
                        )}
                        <LoadingButton
                            loading={isEnqueuing}
                            loadingText="Starting…"
                            variant="primary"
                            onClick={runCleanup}
                        >
                            Run Cleanup
                        </LoadingButton>
                    </div>
                </div>
            </section>

            {/* Content */}
            {loading ? (
                <Spinner size="large" text="Scanning Plex metadata…" center />
            ) : view === 'by-media' ? (
                <>
                    {!hasScanned ? (
                        <div className="text-center py-16 px-6 rounded-lg border border-border-light bg-surface-alt text-sm text-tertiary">
                            <span className="material-symbols-outlined text-3xl mb-2 block opacity-60">
                                cleaning_services
                            </span>
                            <p className="text-primary font-medium mb-1">Ready to scan</p>
                            <p>
                                Click <span className="font-semibold">Refresh</span> above to scan
                                Plex metadata for poster bloat. The scan walks every{' '}
                                <code>.bundle</code> directory under <code>/plex</code> and can take
                                a minute on large libraries.
                            </p>
                        </div>
                    ) : byMedia.error ? (
                        <div className="text-center py-16 px-6 rounded-lg border border-error/40 bg-error/10 text-error text-sm">
                            <span className="material-symbols-outlined text-2xl mb-2 block">
                                error
                            </span>
                            Couldn&apos;t read Plex metadata:{' '}
                            {byMedia.error?.message || String(byMedia.error)}.
                            <div className="text-xs text-secondary mt-2">
                                Check that the <code>/plex</code> mount is configured and the CHUB
                                user can write to <code>/config</code>.
                            </div>
                        </div>
                    ) : bundles.length === 0 ? (
                        <div className="text-center py-16 text-tertiary">
                            No poster variants found. Plex metadata looks clean.
                        </div>
                    ) : (
                        <div className="flex flex-col gap-3">
                            {bundles.map(b => (
                                <BundleCard
                                    key={b.bundle_path}
                                    bundle={b}
                                    selectedPaths={selectedPaths}
                                    onToggleSelect={toggleSelect}
                                    onToggleBundle={toggleBundle}
                                    onPreview={(v, bundle) =>
                                        setPreviewTarget({ variant: v, bundle })
                                    }
                                />
                            ))}
                        </div>
                    )}
                </>
            ) : (
                <>
                    {!hasScanned ? (
                        <div className="text-center py-16 px-6 rounded-lg border border-border-light bg-surface-alt text-sm text-tertiary">
                            <span className="material-symbols-outlined text-3xl mb-2 block opacity-60">
                                cleaning_services
                            </span>
                            <p className="text-primary font-medium mb-1">Ready to scan</p>
                            <p>
                                Click <span className="font-semibold">Refresh</span> above to scan
                                Plex metadata for poster bloat.
                            </p>
                        </div>
                    ) : bloatFlat.error ? (
                        <div className="text-center py-16 px-6 rounded-lg border border-error/40 bg-error/10 text-error text-sm">
                            <span className="material-symbols-outlined text-2xl mb-2 block">
                                error
                            </span>
                            Couldn&apos;t read Plex metadata:{' '}
                            {bloatFlat.error?.message || String(bloatFlat.error)}.
                        </div>
                    ) : bloatItems.length === 0 ? (
                        <div className="text-center py-16 text-tertiary">
                            No bloat variants. Plex metadata is clean.
                        </div>
                    ) : (
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
                            {bloatItems.map(item => (
                                <VariantTile
                                    key={item.path}
                                    variant={{ ...item, active: false }}
                                    selected={selectedPaths.has(item.path)}
                                    onToggleSelect={toggleSelect}
                                    onPreview={v =>
                                        setPreviewTarget({
                                            variant: { ...v, active: false },
                                            bundle: {
                                                bundle_path: item.bundle_path,
                                                rating_key: item.rating_key,
                                                title: item.title,
                                                year: item.year,
                                            },
                                        })
                                    }
                                />
                            ))}
                        </div>
                    )}
                </>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2">
                    <Button
                        variant="ghost"
                        size="small"
                        disabled={page === 0}
                        onClick={() => setPage(p => Math.max(0, p - 1))}
                    >
                        Previous
                    </Button>
                    <span className="text-sm text-secondary">
                        Page {page + 1} of {totalPages}
                    </span>
                    <Button
                        variant="ghost"
                        size="small"
                        disabled={page + 1 >= totalPages}
                        onClick={() => setPage(p => p + 1)}
                    >
                        Next
                    </Button>
                </div>
            )}

            <VariantPreviewModal
                target={previewTarget}
                onClose={() => setPreviewTarget(null)}
                onDelete={handleDeleteVariant}
                onSetActive={(variant, bundle) => setConfirmSetActive({ variant, bundle })}
            />

            <Modal isOpen={!!confirmSetActive} onClose={() => setConfirmSetActive(null)}>
                <Modal.Header>Make this poster active in Plex?</Modal.Header>
                <Modal.Body>
                    <p className="text-sm">
                        This will upload the selected variant to Plex and set it as the active
                        poster for <strong>{confirmSetActive?.bundle?.title || 'this item'}</strong>
                        . The current active variant will become bloat (cleanable from here later).
                    </p>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="secondary" onClick={() => setConfirmSetActive(null)}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={handleSetActive}>
                        Make active
                    </Button>
                </Modal.Footer>
            </Modal>

            <LiveLogModal jobId={liveJobId} onClose={() => setLiveJobId(null)} />
        </div>
    );
};

export default PosterCleanarrPage;
