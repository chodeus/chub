import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { Modal } from '../../components/modals/Modal';
import { Button, LoadingButton, PageHeader } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const PAGE_SIZE = 500; // master-detail needs the full bundle list client-side

// Mode metadata — one row per ImageMaid mode. `action` drives the Run button's
// label + colour. `confirm` means the Run button fires a confirmation modal
// (destructive / permanent operations only). `scope` toggles which modes are
// allowed to send `target_paths`; restore/clear/nothing ignore selection.
const MODE_META = {
    report: {
        label: 'Report',
        action: 'Run scan',
        variant: 'primary',
        confirm: false,
        scopeable: true,
        description: 'Dry run — list bloat images, delete nothing.',
    },
    move: {
        label: 'Move',
        action: 'Move bloat to restore',
        variant: 'warning',
        confirm: false,
        scopeable: true,
        description: 'Relocate bloat to <plex_path>/Poster Cleanarr Restore/ — recoverable.',
    },
    restore: {
        label: 'Restore',
        action: 'Restore files',
        variant: 'success',
        confirm: false,
        scopeable: false,
        description: 'Move everything in the Restore directory back to Metadata/.',
    },
    clear: {
        label: 'Clear',
        action: 'Clear restore dir',
        variant: 'danger',
        confirm: true,
        scopeable: false,
        description: 'Permanently delete everything in the Restore directory. Cannot be undone.',
    },
    remove: {
        label: 'Remove',
        action: 'Delete bloat permanently',
        variant: 'danger',
        confirm: true,
        scopeable: true,
        description: 'Delete bloat from disk directly. Cannot be undone.',
    },
    nothing: {
        label: 'Nothing',
        action: null,
        variant: 'secondary',
        confirm: false,
        scopeable: false,
        description:
            'Skip image processing entirely. Useful for scheduling an orphan-cleanup-only run.',
    },
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
    const tileStyle = {
        borderWidth: '3px',
        borderStyle: 'solid',
        borderColor: isPlex
            ? 'rgba(150,150,160,0.55)'
            : isActive
              ? 'var(--color-success, #32d583)'
              : 'rgba(253,53,92,0.85)',
        boxShadow: isActive && !isPlex ? '0 0 0 2px rgba(50,213,131,0.4)' : 'none',
    };
    const imgStyle = {
        filter: isPlex ? 'grayscale(30%)' : 'none',
        opacity: !isActive && !isPlex ? 0.75 : 1,
    };
    return (
        <div
            className="relative rounded-md overflow-hidden bg-surface cursor-pointer"
            style={tileStyle}
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
                className="w-full h-40 object-cover"
                style={imgStyle}
                onError={e => {
                    e.target.style.display = 'none';
                }}
            />
            {!isActive && !isPlex && (
                <label
                    className="absolute top-1 left-1 rounded px-1 py-0.5 cursor-pointer"
                    style={{ background: 'rgba(0,0,0,0.7)' }}
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
                        className="w-auto mx-auto rounded"
                        style={{ maxHeight: '60vh' }}
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

    // Scan state. Session-only — scanning is an explicit user action, so we
    // intentionally don't persist this. Navigating away and back resets the
    // page to the "Ready to scan" empty state rather than firing a fresh
    // walk-every-bundle on mount.
    const [hasScanned, setHasScanned] = useState(false);

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

    // Persist view/tree state (tab, expansion, selection). `hasScanned` is
    // deliberately excluded — scans must be explicit (see state decl).
    useEffect(() => {
        try {
            localStorage.setItem(
                STATE_KEY,
                JSON.stringify({
                    tab,
                    expandedShows: [...expandedShows],
                    expandedSeasons: [...expandedSeasons],
                    selected,
                })
            );
        } catch {
            // ignore quota / private mode failures
        }
    }, [tab, expandedShows, expandedSeasons, selected]);

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
        const meta = MODE_META[mode];
        if (!meta || !meta.action) return;
        setIsEnqueuing(true);
        try {
            const body = { mode };
            if (meta.scopeable && selectedPaths.size > 0)
                body.target_paths = Array.from(selectedPaths);
            const res = await postersAPI.runPlexMetadataCleanup(body);
            const jobId = res?.data?.job_id;
            if (!jobId) {
                toast.error('Failed to start cleanup');
                return;
            }
            toast.success(`${meta.label} started (job #${jobId})`);
            setLiveJobId(jobId);
            setSelectedPaths(new Set());
        } catch {
            toast.error('Failed to start cleanup');
        } finally {
            setIsEnqueuing(false);
        }
    }, [mode, selectedPaths, toast]);

    const runCleanup = () => {
        if (MODE_META[mode]?.confirm) {
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

    // ---- Per-item bulk actions (right-pane action bar) ----
    const [bulkBusy, setBulkBusy] = useState(false);
    const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
    const [confirmMakeActive, setConfirmMakeActive] = useState(null);

    const deleteSelected = async () => {
        if (bulkBusy || selectedPaths.size === 0) return;
        setBulkBusy(true);
        let ok = 0;
        let failed = 0;
        for (const path of selectedPaths) {
            try {
                await postersAPI.deletePlexMetadataVariant(path);
                ok += 1;
            } catch {
                failed += 1;
            }
        }
        setBulkBusy(false);
        setSelectedPaths(new Set());
        if (failed) toast.error(`Deleted ${ok}, ${failed} failed`);
        else toast.success(`Deleted ${ok} variant${ok === 1 ? '' : 's'}`);
        refreshScan();
    };

    // "Make active & delete rest": user ticks exactly one bloat variant, we
    // promote it to active in Plex and delete every other non-active,
    // non-plex variant in the current detail scope.
    const makeActiveAndDeleteRest = async () => {
        if (bulkBusy || !detail || !confirmMakeActive) return;
        const { keepPath } = confirmMakeActive;
        const keepVariant = detail.variants.find(v => v.path === keepPath);
        if (!keepVariant) {
            toast.error('Selected variant not found — rescan and retry');
            return;
        }
        setBulkBusy(true);
        setConfirmMakeActive(null);
        try {
            await postersAPI.setPlexMetadataActive(detail.bundle.rating_key, keepPath);
        } catch {
            setBulkBusy(false);
            toast.error('Failed to set active poster in Plex');
            return;
        }
        // After swapping active, every formerly-active OR formerly-bloat
        // non-plex variant (except the kept one) becomes deletable.
        const toDelete = detail.variants
            .filter(v => v.path !== keepPath && (v.cls?.source || 'uploads') !== 'plex')
            .map(v => v.path);
        let ok = 0;
        let failed = 0;
        for (const path of toDelete) {
            try {
                await postersAPI.deletePlexMetadataVariant(path);
                ok += 1;
            } catch {
                failed += 1;
            }
        }
        setBulkBusy(false);
        setSelectedPaths(new Set());
        if (failed) toast.error(`Promoted active; deleted ${ok}, ${failed} failed`);
        else toast.success(`Promoted active; deleted ${ok} variant${ok === 1 ? '' : 's'}`);
        refreshScan();
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

            {/* Global cleanup bar — Mode dropdown (all 6 ImageMaid modes) + a Run
                button whose label, colour, and confirm behaviour all track the
                selected mode, so the destructive options are visibly distinct. */}
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
                        {Object.entries(MODE_META).map(([k, m]) => (
                            <option key={k} value={k}>
                                {m.label}
                            </option>
                        ))}
                    </select>
                </label>
                <span className="text-xs text-tertiary" style={{ maxWidth: '420px' }}>
                    {MODE_META[mode]?.description}
                </span>
                <div className="ml-auto flex items-center gap-2">
                    {MODE_META[mode]?.scopeable && (
                        <span className="text-xs text-secondary">
                            {selectedPaths.size > 0
                                ? `${selectedPaths.size} selected`
                                : 'No selection → full library'}
                        </span>
                    )}
                    {MODE_META[mode]?.scopeable && selectedPaths.size > 0 && (
                        <Button variant="ghost" onClick={clearSelection}>
                            Clear
                        </Button>
                    )}
                    <LoadingButton
                        loading={isEnqueuing}
                        loadingText="Starting…"
                        variant={MODE_META[mode]?.variant || 'primary'}
                        onClick={runCleanup}
                        disabled={!hasScanned || !MODE_META[mode]?.action}
                    >
                        {MODE_META[mode]?.action || 'No action'}
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
                    <div
                        className="grid"
                        style={{ gridTemplateColumns: '560px 1fr', minHeight: '680px' }}
                    >
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
                            <div className="overflow-y-auto flex-1" style={{ maxHeight: '620px' }}>
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
                                            <LoadingButton
                                                loading={bulkBusy}
                                                loadingText="Deleting…"
                                                variant="danger"
                                                onClick={() => setConfirmBulkDelete(true)}
                                                disabled={selectedPaths.size === 0}
                                            >
                                                Delete selected
                                            </LoadingButton>
                                            <LoadingButton
                                                loading={bulkBusy}
                                                loadingText="Applying…"
                                                variant="primary"
                                                onClick={() => {
                                                    if (selectedPaths.size !== 1) {
                                                        toast.error(
                                                            'Tick exactly one variant to promote'
                                                        );
                                                        return;
                                                    }
                                                    const [keepPath] = [...selectedPaths];
                                                    setConfirmMakeActive({ keepPath });
                                                }}
                                                disabled={selectedPaths.size !== 1}
                                            >
                                                Make active &amp; delete rest
                                            </LoadingButton>
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
                <Modal.Header>
                    {mode === 'clear'
                        ? 'Clear the restore directory?'
                        : 'Permanently delete bloat variants?'}
                </Modal.Header>
                <Modal.Body>
                    <p className="text-sm">
                        {mode === 'clear' ? (
                            <>
                                This will permanently delete{' '}
                                <strong>every file in the Restore directory</strong>. These were
                                moved there by previous &apos;Move&apos; runs and can currently
                                still be restored; clearing makes them unrecoverable.
                            </>
                        ) : selectedPaths.size > 0 ? (
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
                                disk. This cannot be undone. Consider running <em>Move</em> instead
                                if you&apos;d like the option to restore.
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
                        {MODE_META[mode]?.action || 'Confirm'}
                    </Button>
                </Modal.Footer>
            </Modal>
            <Modal isOpen={confirmBulkDelete} onClose={() => setConfirmBulkDelete(false)}>
                <Modal.Header>
                    Delete {selectedPaths.size} selected variant
                    {selectedPaths.size === 1 ? '' : 's'}?
                </Modal.Header>
                <Modal.Body>
                    <p className="text-sm">
                        Each variant is deleted from disk immediately. This cannot be undone — use{' '}
                        <em>Move</em> mode instead if you want a restore path.
                    </p>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="secondary" onClick={() => setConfirmBulkDelete(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant="danger"
                        onClick={() => {
                            setConfirmBulkDelete(false);
                            deleteSelected();
                        }}
                    >
                        Delete {selectedPaths.size}
                    </Button>
                </Modal.Footer>
            </Modal>
            <Modal isOpen={!!confirmMakeActive} onClose={() => setConfirmMakeActive(null)}>
                <Modal.Header>Promote variant and delete rest?</Modal.Header>
                <Modal.Body>
                    <p className="text-sm">
                        The ticked variant becomes the active poster in Plex for{' '}
                        <strong>{detail?.breadcrumb?.[detail.breadcrumb.length - 1]}</strong>, then
                        every other non-Plex variant in this view is deleted from disk. Plex
                        defaults are left alone. This cannot be undone.
                    </p>
                </Modal.Body>
                <Modal.Footer align="right">
                    <Button variant="secondary" onClick={() => setConfirmMakeActive(null)}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={makeActiveAndDeleteRest}>
                        Make active &amp; delete rest
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
            className="w-6 h-6 shrink-0 inline-flex items-center justify-center rounded-md cursor-pointer"
            style={{
                background: open ? 'var(--primary)' : 'rgba(135,103,247,0.15)',
                color: open ? 'var(--on-color-text, #fff)' : 'var(--primary)',
                border: `1px solid ${open ? 'var(--primary)' : 'rgba(135,103,247,0.4)'}`,
                transition: 'background 100ms',
            }}
        >
            <span
                className="material-symbols-outlined leading-none"
                style={{
                    fontSize: '16px',
                    transform: open ? 'rotate(90deg)' : 'none',
                    transition: 'transform 120ms',
                }}
            >
                chevron_right
            </span>
        </button>
    );
};

// Row-style helpers — selected rows get a left accent bar + faint primary
// tint. Tree depth is encoded in the baseLeftPad argument.
const rowBorder = { borderBottom: '1px solid rgba(var(--border-rgb, 42,48,82), 0.4)' };
const rowStyle = (selected, baseLeftPad) => ({
    ...rowBorder,
    cursor: 'pointer',
    background: selected ? 'rgba(135,103,247,0.15)' : 'transparent',
    borderLeft: selected ? '3px solid var(--primary)' : '3px solid transparent',
    paddingLeft: selected ? `${baseLeftPad - 3}px` : `${baseLeftPad}px`,
    transition: 'background 100ms',
});
const bloatPill = {
    padding: '1px 6px',
    borderRadius: '9999px',
    background: 'rgba(253,53,92,0.2)',
    color: 'var(--error)',
    fontWeight: 600,
    fontSize: '10px',
};
const typeBadge = {
    fontSize: '9px',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    padding: '1px 6px',
    borderRadius: '4px',
    background: 'var(--surface-alt)',
    color: 'var(--text-tertiary)',
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
                className="flex items-center gap-2 pr-2 py-2"
                style={rowStyle(showSelected, 8)}
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
                        <span style={typeBadge}>{bundle.metadata_type_label}</span>
                    </div>
                    <div
                        className="text-secondary flex items-center gap-2"
                        style={{ fontSize: '11px' }}
                    >
                        <span className="truncate">
                            {bundle.library_name || ''} · {bundle.variants.length} variants
                        </span>
                        {bloatCount > 0 && <span style={bloatPill}>● {bloatCount}</span>}
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
                                        className="flex items-center gap-2 pr-2 py-1.5"
                                        style={rowStyle(seasonSelected, 24)}
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
                                        <div
                                            className="flex-1 min-w-0 text-primary"
                                            style={{ fontSize: '13px' }}
                                        >
                                            Season {season.n}
                                            <span
                                                className="text-secondary ml-2"
                                                style={{ fontSize: '10px' }}
                                            >
                                                {season.posters.length} poster
                                                {season.posters.length === 1 ? '' : 's'}
                                                {season.episodes.size > 0
                                                    ? ` · ${season.episodes.size} ep${
                                                          season.episodes.size === 1 ? '' : 's'
                                                      }`
                                                    : ''}
                                                {seasonBloat > 0 && (
                                                    <span className="ml-2" style={bloatPill}>
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
                                                        className="flex items-center gap-2 pr-2 py-1.5"
                                                        style={rowStyle(epSelected, 48)}
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
                                                        <div
                                                            className="flex-1 min-w-0 text-primary"
                                                            style={{ fontSize: '12px' }}
                                                        >
                                                            Episode {episode.n}
                                                            <span
                                                                className="text-secondary ml-2"
                                                                style={{ fontSize: '10px' }}
                                                            >
                                                                {episode.thumbs.length} thumb
                                                                {episode.thumbs.length === 1
                                                                    ? ''
                                                                    : 's'}
                                                                {epBloat > 0 && (
                                                                    <span
                                                                        className="ml-2"
                                                                        style={bloatPill}
                                                                    >
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
