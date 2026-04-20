import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { Modal } from '../../components/modals/Modal';
import { Button, LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const PAGE_SIZE = 500; // master-detail needs the full bundle list client-side

const MODE_LABELS = {
    report: 'Report',
    move: 'Move to trash',
    remove: 'Delete permanently',
};

// localStorage key for persisting scan/filter/tree state across navigations.
const STATE_KEY = 'chub_cleanarr_state_v2';
const loadPersistedState = () => {
    try {
        const raw = localStorage.getItem(STATE_KEY);
        return raw ? JSON.parse(raw) : {};
    } catch {
        return {};
    }
};

const formatBytes = bytes => {
    if (!bytes) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let n = bytes;
    let i = 0;
    while (n >= 1024 && i < u.length - 1) {
        n /= 1024;
        i += 1;
    }
    return `${n.toFixed(1)} ${u[i]}`;
};

// Module-level so reference is stable across renders (fixes exhaustive-deps warning).
const TERMINAL_STATUSES = ['success', 'error', 'cancelled'];

// ---------------------------------------------------------------------------
// Variant path → (level, season, episode, context) classifier
// ---------------------------------------------------------------------------
// Plex stores all artwork under `<bundle>/Uploads/` or `<bundle>/Contents/`.
// For TV shows, the nested path encodes `seasons/N/episodes/M/` so we can
// classify a variant without a second API call.
const classifyVariant = variant => {
    const rel = (variant.path || '').split('.bundle/')[1] || '';
    const source = variant.source || (rel.startsWith('Contents/') ? 'plex' : 'uploads');
    // strip the source prefix so path-matching below is stable
    const body = rel.replace(/^Uploads\//, '').replace(/^Contents\//, '');

    const se = body.match(/posters\/seasons\/(\d+)\/episodes\/(\d+)/);
    if (se) {
        return {
            source,
            level: 'episode',
            season: Number(se[1]),
            episode: Number(se[2]),
            context: `S${String(se[1]).padStart(2, '0')} · E${String(se[2]).padStart(2, '0')}`,
        };
    }
    const s = body.match(/posters\/seasons\/(\d+)\//);
    if (s) {
        return {
            source,
            level: 'season',
            season: Number(s[1]),
            context: `Season ${Number(s[1])}`,
        };
    }
    if (body.startsWith('art/') || body.startsWith('Art/')) {
        return { source, level: 'show', context: 'Background art' };
    }
    if (body.startsWith('banners/') || body.startsWith('Banners/')) {
        return { source, level: 'show', context: 'Banner' };
    }
    return { source, level: 'show', context: 'Show poster' };
};

// Build a tree for a bundle: { show: [], seasons: Map(N -> { posters: [], episodes: Map(M -> { thumbs: [] }) }) }
const buildBundleTree = bundle => {
    const tree = { show: [], seasons: new Map() };
    for (const raw of bundle.variants || []) {
        const cls = classifyVariant(raw);
        const v = { ...raw, cls };
        if (cls.level === 'show') tree.show.push(v);
        else if (cls.level === 'season') {
            if (!tree.seasons.has(cls.season))
                tree.seasons.set(cls.season, { n: cls.season, posters: [], episodes: new Map() });
            tree.seasons.get(cls.season).posters.push(v);
        } else if (cls.level === 'episode') {
            if (!tree.seasons.has(cls.season))
                tree.seasons.set(cls.season, { n: cls.season, posters: [], episodes: new Map() });
            const season = tree.seasons.get(cls.season);
            if (!season.episodes.has(cls.episode))
                season.episodes.set(cls.episode, { n: cls.episode, thumbs: [] });
            season.episodes.get(cls.episode).thumbs.push(v);
        }
    }
    return tree;
};

// ---------------------------------------------------------------------------
// Variant tile — green/red/grey border only, no pill badges.
// ---------------------------------------------------------------------------
const VariantTile = ({ variant, selected, onToggleSelect, onPreview }) => {
    const source = variant.cls?.source || variant.source || 'uploads';
    const isPlex = source === 'plex';
    const isActive = !!variant.active;
    const borderClass = isPlex
        ? 'border-[rgba(150,150,160,0.55)]'
        : isActive
          ? 'border-success ring-2 ring-success/40'
          : 'border-[rgba(253,53,92,0.85)]';
    return (
        <div
            className={`relative rounded-md overflow-hidden border-[3px] ${borderClass} bg-surface cursor-pointer group`}
            onClick={() => onPreview(variant)}
            title={
                isPlex
                    ? 'Plex default — read-only, cannot be deleted'
                    : isActive
                      ? 'Active poster in Plex'
                      : 'Unused (bloat) — candidate for cleanup'
            }
        >
            <img
                src={postersAPI.getPlexVariantUrl(variant.path)}
                alt={variant.filename}
                loading="lazy"
                className={`w-full h-40 object-cover ${isPlex ? 'grayscale-[30%]' : ''} ${
                    !isActive && !isPlex ? 'opacity-75' : ''
                }`}
                onError={e => {
                    e.target.style.display = 'none';
                }}
            />
            {!isActive && !isPlex && (
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
        </div>
    );
};

// ---------------------------------------------------------------------------
// Live cleanup log modal (polling)
// ---------------------------------------------------------------------------
const LiveLogModal = ({ jobId, onClose }) => {
    const [text, setText] = useState('');
    const [status, setStatus] = useState('running');
    const offsetRef = useRef(0);
    const preRef = useRef(null);

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
                        setTimeout(() => {
                            if (preRef.current)
                                preRef.current.scrollTop = preRef.current.scrollHeight;
                        }, 0);
                    }
                    if (data.status) setStatus(data.status);
                    if (TERMINAL_STATUSES.includes(data.status)) return;
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

// ---------------------------------------------------------------------------
// Per-variant preview modal (full-size image + actions)
// ---------------------------------------------------------------------------
const VariantPreviewModal = ({ target, onClose, onDelete, onSetActive }) => {
    if (!target) return null;
    const { variant, bundle } = target;
    const source = variant.cls?.source || variant.source || 'uploads';
    const isPlex = source === 'plex';
    const isActive = variant.active;
    const statusLabel = isPlex ? (
        <span className="text-tertiary">Plex default (read-only)</span>
    ) : isActive ? (
        <span className="text-success">Active</span>
    ) : (
        <span className="text-error">Bloat</span>
    );
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
                        {formatBytes(variant.size)} · {statusLabel}
                        {variant.cls?.context ? ` · ${variant.cls.context}` : ''}
                    </div>
                </div>
            </Modal.Body>
            <Modal.Footer align="right">
                {!isActive && bundle?.rating_key && (
                    <Button variant="primary" onClick={() => onSetActive(variant, bundle)}>
                        Make active in Plex
                    </Button>
                )}
                {!isActive && !isPlex && (
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

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
const PosterCleanarrPage = () => {
    const toast = useToast();
    const persisted = useMemo(() => loadPersistedState(), []);

    // Action-bar state (global bulk cleanup flow — Report/Move/Remove).
    const [mode, setMode] = useState('report');

    // Scan state. `hasScanned` persists — once the user has triggered a
    // scan in this browser, we auto-refresh on remount.
    const [hasScanned, setHasScanned] = useState(persisted.hasScanned ?? false);

    // Tab + search on the left pane.
    const [tab, setTab] = useState(persisted.tab || 'all');
    const [search, setSearch] = useState('');

    // Tree expansion (persisted so the user's open branches survive a reload).
    const [expandedShows, setExpandedShows] = useState(
        () => new Set(persisted.expandedShows || [])
    );
    const [expandedSeasons, setExpandedSeasons] = useState(
        () => new Set(persisted.expandedSeasons || [])
    );

    // Selected node in the left tree.
    //   { kind: 'show' | 'season' | 'episode', ratingKey, season?, episode? }
    const [selected, setSelected] = useState(persisted.selected || null);

    // Per-variant bulk selection (checkbox on bloat tiles).
    const [selectedPaths, setSelectedPaths] = useState(new Set());

    // Modals.
    const [previewTarget, setPreviewTarget] = useState(null);
    const [confirmSetActive, setConfirmSetActive] = useState(null);
    const [confirmRemove, setConfirmRemove] = useState(false);
    const [liveJobId, setLiveJobId] = useState(null);
    const [isEnqueuing, setIsEnqueuing] = useState(false);

    // ---- Scan data ----
    const byMedia = useApiData({
        apiFunction: useCallback(
            () => postersAPI.listPlexMetadataByMedia({ limit: PAGE_SIZE, offset: 0 }),
            []
        ),
        dependencies: [],
        options: { showErrorToast: false, immediate: false },
    });

    const bundles = useMemo(() => byMedia.data?.data?.bundles || [], [byMedia.data]);
    const stats = useMemo(() => byMedia.data?.data?.stats || null, [byMedia.data]);
    const loading = byMedia.isLoading;

    // Build all trees once per scan payload.
    const bundleTrees = useMemo(() => {
        const m = new Map();
        for (const b of bundles) m.set(b.rating_key, buildBundleTree(b));
        return m;
    }, [bundles]);

    // Persist view/tree state.
    useEffect(() => {
        try {
            localStorage.setItem(
                STATE_KEY,
                JSON.stringify({
                    hasScanned,
                    tab,
                    expandedShows: [...expandedShows],
                    expandedSeasons: [...expandedSeasons],
                    selected,
                })
            );
        } catch {
            // ignore quota / private mode failures
        }
    }, [hasScanned, tab, expandedShows, expandedSeasons, selected]);

    // Auto-refresh on mount if the user has scanned before.
    const didMountRefreshRef = useRef(false);
    useEffect(() => {
        if (didMountRefreshRef.current) return;
        if (!hasScanned) return;
        didMountRefreshRef.current = true;
        byMedia.refresh();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const refreshScan = useCallback(() => {
        if (!hasScanned) setHasScanned(true);
        byMedia.refresh();
    }, [byMedia, hasScanned]);

    // ---- Tab filtering ----
    const filteredBundles = useMemo(() => {
        return bundles.filter(b => {
            if (tab !== 'all' && b.metadata_type_label !== tab) return false;
            if (search && !(b.title || '').toLowerCase().includes(search.toLowerCase()))
                return false;
            return true;
        });
    }, [bundles, tab, search]);

    // ---- Derived: variants visible in the right pane ----
    const detail = useMemo(() => {
        if (!selected) return null;
        const bundle = bundles.find(b => b.rating_key === selected.ratingKey);
        if (!bundle) return null;
        const tree = bundleTrees.get(bundle.rating_key);
        if (!tree) return null;
        if (selected.kind === 'show') {
            const variants = tree.show;
            return { bundle, variants, breadcrumb: [bundle.title] };
        }
        if (selected.kind === 'season') {
            const season = tree.seasons.get(selected.season);
            return {
                bundle,
                variants: season?.posters || [],
                breadcrumb: [bundle.title, `Season ${selected.season}`],
            };
        }
        if (selected.kind === 'episode') {
            const season = tree.seasons.get(selected.season);
            const ep = season?.episodes.get(selected.episode);
            return {
                bundle,
                variants: ep?.thumbs || [],
                breadcrumb: [
                    bundle.title,
                    `Season ${selected.season}`,
                    `Episode ${selected.episode}`,
                ],
            };
        }
        return null;
    }, [selected, bundles, bundleTrees]);

    // ---- Tree expansion / selection handlers ----
    const toggleShow = useCallback(rk => {
        setExpandedShows(prev => {
            const next = new Set(prev);
            if (next.has(rk)) next.delete(rk);
            else next.add(rk);
            return next;
        });
    }, []);

    const toggleSeason = useCallback((rk, n) => {
        const key = `${rk}:${n}`;
        setExpandedSeasons(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    }, []);

    const selectNode = useCallback(node => {
        setSelected(node);
        setSelectedPaths(new Set());
    }, []);

    // ---- Variant actions ----
    const toggleSelect = useCallback(variant => {
        setSelectedPaths(prev => {
            const next = new Set(prev);
            if (next.has(variant.path)) next.delete(variant.path);
            else next.add(variant.path);
            return next;
        });
    }, []);

    const selectAllBloat = () => {
        if (!detail) return;
        const next = new Set(selectedPaths);
        for (const v of detail.variants) {
            if (!v.active && (v.cls?.source || 'uploads') !== 'plex') next.add(v.path);
        }
        setSelectedPaths(next);
    };

    const clearSelection = () => setSelectedPaths(new Set());

    const executeCleanup = useCallback(async () => {
        setIsEnqueuing(true);
        try {
            const body = { mode };
            if (selectedPaths.size > 0) body.target_paths = Array.from(selectedPaths);
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
    }, [mode, selectedPaths, toast]);

    const runCleanup = () => {
        if (mode === 'remove') {
            setConfirmRemove(true);
            return;
        }
        executeCleanup();
    };

    const handleDeleteVariant = async variant => {
        try {
            await postersAPI.deletePlexMetadataVariant(variant.path);
            toast.success('Variant deleted');
            setPreviewTarget(null);
            refreshScan();
        } catch {
            toast.error('Failed to delete variant');
        }
    };

    const handleSetActiveRequest = (variant, bundle) => {
        setConfirmSetActive({ variant, bundle });
    };

    const handleSetActive = async () => {
        if (!confirmSetActive) return;
        const { variant, bundle } = confirmSetActive;
        try {
            await postersAPI.setPlexMetadataActive(bundle.rating_key, variant.path);
            toast.success('Active poster updated in Plex');
            setConfirmSetActive(null);
            setPreviewTarget(null);
            refreshScan();
        } catch {
            toast.error('Failed to update active poster');
        }
    };

    // ---- Render ----
    const bloatInDetail = detail
        ? detail.variants.filter(v => !v.active && (v.cls?.source || 'uploads') !== 'plex').length
        : 0;
    const plexInDetail = detail
        ? detail.variants.filter(v => (v.cls?.source || 'uploads') === 'plex').length
        : 0;
    const activeInDetail = detail ? detail.variants.filter(v => v.active).length : 0;
    const reclaimableBytes = detail
        ? detail.variants
              .filter(v => !v.active && (v.cls?.source || 'uploads') !== 'plex')
              .reduce((s, v) => s + (v.size || 0), 0)
        : 0;

    return (
        <div className="flex flex-col gap-4">
            <PageHeader
                icon="cleaning_services"
                title="Poster Cleanarr"
                description="Review Plex poster variants and clean up unused (bloat) images."
            />

            {/* Global summary stats (only when a scan exists). */}
            {hasScanned && stats && (
                <div className="text-sm text-secondary">
                    {stats.bundle_count} items · {stats.variant_count} variants ·{' '}
                    <span className="text-error">{stats.bloat_count} bloat</span> ·{' '}
                    {formatBytes(stats.bloat_size)} reclaimable
                </div>
            )}

            {/* Global cleanup bar (Mode + Run) — for the "clean everything right now" path. */}
            <section className="rounded-lg bg-surface border border-border p-3 flex flex-wrap items-center gap-3">
                <Button variant="ghost" onClick={refreshScan} disabled={loading}>
                    <span className="material-symbols-outlined text-base">refresh</span>
                    Refresh scan
                </Button>
                <div className="h-6 w-px bg-border mx-1" aria-hidden="true" />
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
                <div className="ml-auto flex items-center gap-2">
                    <span className="text-xs text-secondary">
                        {selectedPaths.size > 0
                            ? `${selectedPaths.size} selected`
                            : 'No selection → full library'}
                    </span>
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
                        disabled={!hasScanned}
                    >
                        Run Cleanup
                    </LoadingButton>
                </div>
            </section>

            {/* Scan empty / loading / loaded states */}
            {!hasScanned ? (
                <div className="text-center py-16 px-6 rounded-lg border border-border-light bg-surface-alt text-sm text-tertiary">
                    <span className="material-symbols-outlined text-3xl mb-2 block opacity-60">
                        cleaning_services
                    </span>
                    <p className="text-primary font-medium mb-1">Ready to scan</p>
                    <p>
                        Click <span className="font-semibold">Refresh scan</span> above to scan Plex
                        metadata. Walks every <code>.bundle</code> under <code>/plex</code>; can
                        take a minute on large libraries.
                    </p>
                </div>
            ) : byMedia.error ? (
                <div className="text-center py-16 px-6 rounded-lg border border-error/40 bg-error/10 text-error text-sm">
                    Couldn&apos;t read Plex metadata:{' '}
                    {byMedia.error?.message || String(byMedia.error)}.
                </div>
            ) : loading && bundles.length === 0 ? (
                <Spinner size="medium" text="Scanning Plex metadata..." center />
            ) : bundles.length === 0 ? (
                <div className="text-center py-16 text-tertiary">
                    No poster variants found. Plex metadata looks clean.
                </div>
            ) : (
                // ---- Master-detail split ----
                <section className="rounded-lg border border-border overflow-hidden bg-surface">
                    <div className="grid grid-cols-1 md:grid-cols-[340px_1fr] min-h-[680px]">
                        {/* Left pane */}
                        <div className="flex flex-col border-r border-border">
                            {/* Tabs */}
                            <div className="flex gap-1 p-2 border-b border-border">
                                {[
                                    ['all', 'All'],
                                    ['movie', 'Movies'],
                                    ['show', 'Shows'],
                                    ['collection', 'Collections'],
                                ].map(([v, label]) => (
                                    <button
                                        key={v}
                                        type="button"
                                        onClick={() => setTab(v)}
                                        className={`flex-1 px-2 py-1.5 text-xs rounded-md cursor-pointer border ${
                                            tab === v
                                                ? 'bg-primary/20 text-primary border-primary/40'
                                                : 'bg-transparent text-secondary border-transparent hover:bg-surface-alt'
                                        }`}
                                    >
                                        {label}
                                    </button>
                                ))}
                            </div>
                            <input
                                type="search"
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                placeholder="Search titles..."
                                className="m-2 px-3 py-1.5 rounded bg-surface-alt border border-border text-sm"
                            />
                            {/* Tree list */}
                            <div className="overflow-y-auto flex-1 max-h-[620px]">
                                {filteredBundles.length === 0 ? (
                                    <div className="text-center text-tertiary text-sm p-4">
                                        No matches
                                    </div>
                                ) : (
                                    filteredBundles.map(bundle => (
                                        <BundleTreeRow
                                            key={bundle.rating_key}
                                            bundle={bundle}
                                            tree={bundleTrees.get(bundle.rating_key)}
                                            selected={selected}
                                            expandedShows={expandedShows}
                                            expandedSeasons={expandedSeasons}
                                            onToggleShow={toggleShow}
                                            onToggleSeason={toggleSeason}
                                            onSelect={selectNode}
                                        />
                                    ))
                                )}
                            </div>
                        </div>
                        {/* Right pane */}
                        <div className="flex flex-col min-w-0">
                            {!detail ? (
                                <div className="p-12 text-center text-tertiary">
                                    Select an item on the left. Shows have chevrons to drill into
                                    seasons and episodes.
                                </div>
                            ) : (
                                <>
                                    <header className="p-4 border-b border-border">
                                        <div className="text-xs text-secondary mb-1 flex items-center gap-2">
                                            {detail.breadcrumb.map((crumb, i) => (
                                                <React.Fragment key={i}>
                                                    {i > 0 && (
                                                        <span className="text-tertiary">›</span>
                                                    )}
                                                    <span
                                                        className={
                                                            i < detail.breadcrumb.length - 1
                                                                ? 'cursor-pointer hover:text-primary'
                                                                : ''
                                                        }
                                                        onClick={() => {
                                                            if (i >= detail.breadcrumb.length - 1)
                                                                return;
                                                            if (i === 0)
                                                                selectNode({
                                                                    kind: 'show',
                                                                    ratingKey:
                                                                        detail.bundle.rating_key,
                                                                });
                                                            else if (i === 1)
                                                                selectNode({
                                                                    kind: 'season',
                                                                    ratingKey:
                                                                        detail.bundle.rating_key,
                                                                    season: selected.season,
                                                                });
                                                        }}
                                                    >
                                                        {crumb}
                                                    </span>
                                                </React.Fragment>
                                            ))}
                                        </div>
                                        <h3 className="text-xl font-semibold text-primary m-0">
                                            {detail.breadcrumb[detail.breadcrumb.length - 1]}
                                        </h3>
                                        <div className="text-xs text-secondary mt-1">
                                            {detail.variants.length} variants ·{' '}
                                            <span className="text-success">
                                                {activeInDetail} active
                                            </span>{' '}
                                            ·{' '}
                                            <span className="text-error">
                                                {bloatInDetail} bloat
                                            </span>
                                            {plexInDetail > 0 && (
                                                <>
                                                    {' '}
                                                    ·{' '}
                                                    <span className="text-tertiary">
                                                        {plexInDetail} plex
                                                    </span>
                                                </>
                                            )}
                                            {bloatInDetail > 0 && (
                                                <> · {formatBytes(reclaimableBytes)} reclaimable</>
                                            )}
                                        </div>
                                    </header>
                                    <div className="flex-1 overflow-y-auto p-4">
                                        {detail.variants.length === 0 ? (
                                            <div className="text-center text-tertiary py-12">
                                                No variants at this level.
                                            </div>
                                        ) : (
                                            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                                                {detail.variants.map(v => (
                                                    <VariantTile
                                                        key={v.path}
                                                        variant={v}
                                                        selected={selectedPaths.has(v.path)}
                                                        onToggleSelect={toggleSelect}
                                                        onPreview={variant =>
                                                            setPreviewTarget({
                                                                variant,
                                                                bundle: detail.bundle,
                                                            })
                                                        }
                                                    />
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    {/* Per-item bulk action bar */}
                                    {detail.variants.length > 0 && (
                                        <div className="flex flex-wrap items-center gap-2 p-3 border-t border-border bg-surface-alt">
                                            <span className="text-xs text-secondary mr-auto">
                                                {selectedPaths.size > 0
                                                    ? `${selectedPaths.size} selected`
                                                    : `${bloatInDetail} bloat available`}
                                            </span>
                                            <Button
                                                variant="ghost"
                                                onClick={selectAllBloat}
                                                disabled={bloatInDetail === 0}
                                            >
                                                Select all bloat
                                            </Button>
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                </section>
            )}

            <VariantPreviewModal
                target={previewTarget}
                onClose={() => setPreviewTarget(null)}
                onDelete={handleDeleteVariant}
                onSetActive={handleSetActiveRequest}
            />
            <Modal isOpen={!!confirmSetActive} onClose={() => setConfirmSetActive(null)}>
                <Modal.Header>Make active in Plex?</Modal.Header>
                <Modal.Body>
                    <p className="text-sm">
                        This will set the selected variant as the active poster for{' '}
                        <strong>{confirmSetActive?.bundle?.title || 'this item'}</strong> in Plex.
                        The currently-active variant becomes bloat.
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
            <Modal isOpen={confirmRemove} onClose={() => setConfirmRemove(false)}>
                <Modal.Header>Permanently delete bloat variants?</Modal.Header>
                <Modal.Body>
                    <p className="text-sm">
                        {selectedPaths.size > 0 ? (
                            <>
                                This will permanently delete <strong>{selectedPaths.size}</strong>{' '}
                                selected variant
                                {selectedPaths.size === 1 ? '' : 's'} from disk. This cannot be
                                undone.
                            </>
                        ) : (
                            <>
                                This will permanently delete{' '}
                                <strong>every bloat variant across your entire library</strong> from
                                disk. This cannot be undone. Consider running <em>Move to trash</em>{' '}
                                instead if you&apos;d like the option to restore.
                            </>
                        )}
                    </p>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="secondary" onClick={() => setConfirmRemove(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant="danger"
                        onClick={() => {
                            setConfirmRemove(false);
                            executeCleanup();
                        }}
                    >
                        Delete permanently
                    </Button>
                </Modal.Footer>
            </Modal>
            <LiveLogModal jobId={liveJobId} onClose={() => setLiveJobId(null)} />
        </div>
    );
};

// ---------------------------------------------------------------------------
// BundleTreeRow — render a bundle row + its expanded seasons/episodes
// ---------------------------------------------------------------------------
const Chevron = ({ open, visible, onClick }) => {
    if (!visible) return <span className="w-6 h-6 shrink-0 inline-block" aria-hidden="true" />;
    return (
        <button
            type="button"
            aria-label={open ? 'Collapse' : 'Expand'}
            aria-expanded={open}
            onClick={e => {
                e.stopPropagation();
                onClick();
            }}
            className={`w-6 h-6 shrink-0 inline-flex items-center justify-center rounded-md border cursor-pointer transition-colors ${
                open
                    ? 'bg-primary text-on-color border-primary'
                    : 'bg-primary/15 text-primary border-primary/40 hover:bg-primary/25'
            }`}
        >
            <span
                className="material-symbols-outlined text-[16px] leading-none"
                style={{
                    transform: open ? 'rotate(90deg)' : 'none',
                    transition: 'transform 120ms',
                }}
            >
                chevron_right
            </span>
        </button>
    );
};

const BundleTreeRow = ({
    bundle,
    tree,
    selected,
    expandedShows,
    expandedSeasons,
    onToggleShow,
    onToggleSeason,
    onSelect,
}) => {
    const isShow = bundle.metadata_type_label === 'show';
    const showExpanded = expandedShows.has(bundle.rating_key);
    const bloatCount = (tree?.show || [])
        .concat(
            [...(tree?.seasons.values() || [])].flatMap(s =>
                s.posters.concat([...s.episodes.values()].flatMap(e => e.thumbs))
            )
        )
        .filter(v => !v.active && (v.cls?.source || 'uploads') !== 'plex').length;

    const showSelected = selected?.kind === 'show' && selected.ratingKey === bundle.rating_key;

    return (
        <>
            <div
                className={`flex items-center gap-2 px-2 py-2 border-b border-border/40 cursor-pointer ${
                    showSelected
                        ? 'bg-primary/15 border-l-[3px] border-l-primary pl-[5px]'
                        : 'hover:bg-surface-alt/60'
                }`}
                onClick={() => onSelect({ kind: 'show', ratingKey: bundle.rating_key })}
            >
                <Chevron
                    open={showExpanded}
                    visible={isShow}
                    onClick={() => onToggleShow(bundle.rating_key)}
                />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 text-sm font-medium text-primary">
                        <span className="truncate">
                            {bundle.title || '(unknown)'}
                            {bundle.year ? ` (${bundle.year})` : ''}
                        </span>
                        <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-surface-alt text-tertiary">
                            {bundle.metadata_type_label}
                        </span>
                    </div>
                    <div className="text-[11px] text-secondary flex items-center gap-2">
                        <span className="truncate">
                            {bundle.library_name || ''} · {bundle.variants.length} variants
                        </span>
                        {bloatCount > 0 && (
                            <span className="px-1.5 py-0.5 rounded-full bg-error/20 text-error text-[10px] font-semibold">
                                ● {bloatCount}
                            </span>
                        )}
                    </div>
                </div>
            </div>
            {isShow && showExpanded && tree && (
                <>
                    {[...tree.seasons.values()]
                        .sort((a, b) => a.n - b.n)
                        .map(season => {
                            const seasonKey = `${bundle.rating_key}:${season.n}`;
                            const seasonExpanded = expandedSeasons.has(seasonKey);
                            const seasonSelected =
                                selected?.kind === 'season' &&
                                selected.ratingKey === bundle.rating_key &&
                                selected.season === season.n;
                            const seasonBloat = season.posters
                                .concat([...season.episodes.values()].flatMap(e => e.thumbs))
                                .filter(
                                    v => !v.active && (v.cls?.source || 'uploads') !== 'plex'
                                ).length;
                            return (
                                <React.Fragment key={season.n}>
                                    <div
                                        className={`flex items-center gap-2 pl-6 pr-2 py-1.5 border-b border-border/40 cursor-pointer ${
                                            seasonSelected
                                                ? 'bg-primary/15 border-l-[3px] border-l-primary pl-[22px]'
                                                : 'hover:bg-surface-alt/60'
                                        }`}
                                        onClick={() =>
                                            onSelect({
                                                kind: 'season',
                                                ratingKey: bundle.rating_key,
                                                season: season.n,
                                            })
                                        }
                                    >
                                        <Chevron
                                            open={seasonExpanded}
                                            visible={season.episodes.size > 0}
                                            onClick={() =>
                                                onToggleSeason(bundle.rating_key, season.n)
                                            }
                                        />
                                        <div className="flex-1 min-w-0 text-[13px] text-primary">
                                            Season {season.n}
                                            <span className="text-[10px] text-secondary ml-2">
                                                {season.posters.length} poster
                                                {season.posters.length === 1 ? '' : 's'}
                                                {season.episodes.size > 0
                                                    ? ` · ${season.episodes.size} ep${
                                                          season.episodes.size === 1 ? '' : 's'
                                                      }`
                                                    : ''}
                                                {seasonBloat > 0 && (
                                                    <span className="ml-2 px-1.5 py-0.5 rounded-full bg-error/20 text-error font-semibold">
                                                        ● {seasonBloat}
                                                    </span>
                                                )}
                                            </span>
                                        </div>
                                    </div>
                                    {seasonExpanded &&
                                        [...season.episodes.values()]
                                            .sort((a, b) => a.n - b.n)
                                            .map(episode => {
                                                const epSelected =
                                                    selected?.kind === 'episode' &&
                                                    selected.ratingKey === bundle.rating_key &&
                                                    selected.season === season.n &&
                                                    selected.episode === episode.n;
                                                const epBloat = episode.thumbs.filter(
                                                    v =>
                                                        !v.active &&
                                                        (v.cls?.source || 'uploads') !== 'plex'
                                                ).length;
                                                return (
                                                    <div
                                                        key={episode.n}
                                                        className={`flex items-center gap-2 pl-12 pr-2 py-1.5 border-b border-border/40 cursor-pointer ${
                                                            epSelected
                                                                ? 'bg-primary/15 border-l-[3px] border-l-primary pl-[46px]'
                                                                : 'hover:bg-surface-alt/60'
                                                        }`}
                                                        onClick={() =>
                                                            onSelect({
                                                                kind: 'episode',
                                                                ratingKey: bundle.rating_key,
                                                                season: season.n,
                                                                episode: episode.n,
                                                            })
                                                        }
                                                    >
                                                        <span className="w-6 h-6 shrink-0" />
                                                        <div className="flex-1 min-w-0 text-[12px] text-primary">
                                                            Episode {episode.n}
                                                            <span className="text-[10px] text-secondary ml-2">
                                                                {episode.thumbs.length} thumb
                                                                {episode.thumbs.length === 1
                                                                    ? ''
                                                                    : 's'}
                                                                {epBloat > 0 && (
                                                                    <span className="ml-2 px-1.5 py-0.5 rounded-full bg-error/20 text-error font-semibold">
                                                                        ● {epBloat}
                                                                    </span>
                                                                )}
                                                            </span>
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                </React.Fragment>
                            );
                        })}
                </>
            )}
        </>
    );
};

export default PosterCleanarrPage;
