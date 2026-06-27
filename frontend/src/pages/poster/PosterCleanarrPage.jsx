import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useApiData } from '../../hooks/useApiData.js';
import { useToast } from '../../contexts/ToastContext.jsx';
import { postersAPI } from '../../utils/api/posters.js';
import { Modal } from '../../components/modals/Modal';
import { Button, LoadingButton } from '../../components/ui/index.js';
import Spinner from '../../components/ui/Spinner.jsx';

const PAGE_SIZE = 500; // master-detail needs the full bundle list client-side

// Mode metadata — one row per cleanup mode. `action` drives the Run button's
// label + colour. `confirm` means the Run button fires a confirmation modal
// (destructive / permanent operations only). `scope` toggles which modes are
// allowed to send `target_paths`; restore/clear/nothing ignore selection.
const MODE_META = {
    report: {
        label: 'Report',
        action: 'Run scan',
        variant: 'primary',
        confirm: false,
        scopeable: false,
        description: 'List bloat images in the UI. Nothing is deleted.',
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

// Poll a background job's log-tail until it reaches a terminal status. Resolves
// with the final status (or undefined once `token.cancelled` flips, e.g. on
// unmount or a superseding scan). Shared by the metadata-scan and kometa-scan
// flows so neither walks the filesystem on the server's event loop.
function pollJobUntilDone(jobId, token) {
    return new Promise(resolve => {
        let offset = 0;
        const poll = () => {
            if (token.cancelled) return resolve();
            postersAPI
                .tailJobLog(jobId, offset)
                .then(res => {
                    if (token.cancelled) return resolve();
                    const data = res?.data || {};
                    if (typeof data.next_offset === 'number') offset = data.next_offset;
                    if (TERMINAL_STATUSES.includes(data.status)) return resolve(data.status);
                    setTimeout(poll, 1500);
                })
                .catch(() => {
                    if (!token.cancelled) setTimeout(poll, 3000);
                });
        };
        poll();
    });
}

// ---------------------------------------------------------------------------
// Stale-duplicate → bundle matching helpers
// ---------------------------------------------------------------------------
// A stale asset folder is identified by its {tvdb/tmdb} id; the scan resolves
// that to a Plex rating_key + title/year via plex_media_cache. The cached
// rating_key frequently drifts from the live bundle scan (a re-add/re-match
// mints a new key), so we match by rating_key first, then fall back to the
// Plex title+year, then the folder's own parsed title+year.
const normTitle = t => (t || '').toLowerCase().replace(/[^a-z0-9]/g, '');
const titleYearKey = (title, year) => `${normTitle(title)}|${year ?? ''}`;
// Parse "Show Name (2019) {tvdb-123}" → { title: 'Show Name', year: 2019 }.
const parseFolderTitleYear = name => {
    const noId = (name || '').replace(/\s*\{[^}]*\}\s*$/, '');
    const ym = noId.match(/\((\d{4})\)\s*$/);
    const year = ym ? Number(ym[1]) : null;
    const title = noId.replace(/\s*\(\d{4}\)\s*$/, '').trim();
    return { title, year };
};

// Matches Tailwind's `md` breakpoint (already used by the thumbnail grid below).
// Below this we collapse the master-detail layout into a single column and
// toggle between list/detail views based on selection.
const MOBILE_QUERY = '(max-width: 767px)';
const useIsMobile = () => {
    const [isMobile, setIsMobile] = useState(() =>
        typeof window !== 'undefined' ? window.matchMedia(MOBILE_QUERY).matches : false
    );
    useEffect(() => {
        if (typeof window === 'undefined') return undefined;
        const mq = window.matchMedia(MOBILE_QUERY);
        const handler = e => setIsMobile(e.matches);
        mq.addEventListener('change', handler);
        return () => mq.removeEventListener('change', handler);
    }, []);
    return isMobile;
};

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

    // Category from the top-level folder. Background art / banners can be set
    // per-season too, so the season segment isn't unique to posters/.
    const category =
        body.startsWith('art/') || body.startsWith('Art/')
            ? 'Background art'
            : body.startsWith('banners/') || body.startsWith('Banners/')
              ? 'Banner'
              : 'Poster';

    // Match the season/episode segment wherever it sits (posters/seasons/…,
    // art/seasons/…, banners/seasons/…) so per-season art and banners nest
    // under their season instead of piling onto the show node.
    const se = body.match(/seasons\/(\d+)\/episodes\/(\d+)/);
    if (se) {
        return {
            source,
            level: 'episode',
            season: Number(se[1]),
            episode: Number(se[2]),
            context: `S${String(se[1]).padStart(2, '0')} · E${String(se[2]).padStart(2, '0')}`,
        };
    }
    const s = body.match(/seasons\/(\d+)\//);
    if (s) {
        const n = Number(s[1]);
        return {
            source,
            level: 'season',
            season: n,
            context: category === 'Poster' ? `Season ${n}` : `Season ${n} · ${category}`,
        };
    }
    if (category === 'Background art') {
        return { source, level: 'show', context: 'Background art' };
    }
    if (category === 'Banner') {
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
            ? '#3b3d72'
            : isActive
              ? 'var(--color-success, #6cbc66)'
              : 'rgba(253,53,92,0.85)',
        boxShadow: isActive && !isPlex ? '0 0 0 2px rgba(50,213,131,0.4)' : 'none',
        // Poster aspect ratio — lets the full image show without cropping the
        // top/bottom. Non-poster variants (art/banners/episode thumbs) render
        // letterboxed via object-contain on the <img>, which is fine because
        // those are the minority and previewing them whole beats cropping.
        aspectRatio: '2 / 3',
        // content-box so the 3px border wraps the 2:3 content area instead of
        // eating into it. border-box (default) would compress the inner area
        // to 0.660 aspect and create a 1-3px letterbox at top/bottom of a
        // perfectly-sized poster.
        boxSizing: 'content-box',
    };
    const imgStyle = {
        filter: isPlex ? 'grayscale(30%)' : 'none',
        opacity: !isActive && !isPlex ? 0.75 : 1,
        // display:block prevents the default inline-img baseline gap under
        // the image.
        display: 'block',
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
                className="w-full h-full object-contain"
                style={imgStyle}
                onError={e => {
                    e.target.style.display = 'none';
                }}
            />
            {!isActive && !isPlex && (
                <button
                    type="button"
                    aria-label={selected ? 'Deselect variant' : 'Select variant'}
                    onClick={e => {
                        e.stopPropagation();
                        onToggleSelect(variant);
                    }}
                    className={`absolute top-1.5 left-1.5 flex items-center justify-center w-[18px] h-[18px] rounded-[4px] border transition-colors ${
                        selected ? 'bg-primary border-primary' : 'border-fg-subtle'
                    }`}
                    style={{ background: selected ? undefined : 'rgba(12,8,32,0.55)' }}
                >
                    {selected && (
                        <span className="material-symbols-outlined text-white text-[13px] leading-none">
                            check
                        </span>
                    )}
                </button>
            )}
            <span
                className={`absolute bottom-0 left-0 right-0 px-1.5 py-1 font-mono text-[8.5px] font-semibold tracking-[0.3px] ${
                    isActive ? 'text-success' : isPlex ? 'text-fg-subtle' : 'text-error'
                }`}
                style={{
                    background: 'linear-gradient(to top, rgba(12,8,32,0.85), transparent)',
                }}
            >
                {isActive ? 'active' : isPlex ? 'plex' : 'bloat'}
            </span>
        </div>
    );
};

// Mode-bar checkbox styled to the mock: a 17px rounded box that fills with the
// brand colour + a check glyph when on (replaces the native browser checkbox so
// it matches the rest of the redesign).
const ModeCheck = ({ label, checked, disabled, onChange, title }) => (
    <button
        type="button"
        disabled={disabled}
        onClick={() => onChange(!checked)}
        title={title}
        className={`flex items-center gap-2 text-[13px] text-fg ${
            disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'
        }`}
    >
        <span
            className={`flex items-center justify-center w-[17px] h-[17px] rounded-[4px] border transition-colors ${
                checked ? 'bg-primary border-primary' : 'bg-transparent border-[#3b3d72]'
            }`}
        >
            {checked && (
                <span className="material-symbols-outlined text-white text-[13px] leading-none">
                    check
                </span>
            )}
        </span>
        {label}
    </button>
);

// ---------------------------------------------------------------------------
// Live cleanup log modal (polling)
// ---------------------------------------------------------------------------
const LiveLogModal = ({ jobId, onClose, onCompleted }) => {
    const [text, setText] = useState('');
    const [status, setStatus] = useState('running');
    const offsetRef = useRef(0);
    const preRef = useRef(null);
    // Guard so onCompleted fires exactly once per job — the polling loop
    // exits as soon as it sees a terminal status, but we still want a single
    // notification edge for the parent.
    const completedFiredRef = useRef(false);

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
        completedFiredRef.current = false;
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
                    if (TERMINAL_STATUSES.includes(data.status)) {
                        if (!completedFiredRef.current && onCompleted) {
                            completedFiredRef.current = true;
                            onCompleted(jobId, data.status);
                        }
                        return;
                    }
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
    }, [jobId, onCompleted]);

    const terminal = TERMINAL_STATUSES.includes(status);

    return (
        <Modal isOpen={!!jobId} onClose={onClose} size="large">
            <Modal.Header>Cleanup job #{jobId}</Modal.Header>
            <Modal.Body>
                <div className="flex flex-col gap-3">
                    <div className="text-sm text-fg-muted">
                        Status: <span className="font-medium text-fg">{status}</span>
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
        <span className="text-fg-subtle">Plex default (read-only)</span>
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
                    <div className="text-xs text-fg-muted font-mono break-all">{variant.path}</div>
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
    const isMobile = useIsMobile();

    // Action-bar state (global bulk cleanup flow — Report/Move/Remove).
    const [mode, setMode] = useState('report');
    const [cleanBloat, setCleanBloat] = useState(true);
    const [cleanStale, setCleanStale] = useState(false);
    const [cleanOrphan, setCleanOrphan] = useState(false);
    // Narrow the bloat pass to Kometa overlay images only (matched by EXIF tag),
    // sparing user-uploaded customs. Only applies when bloat is running.
    const [cleanOverlaysOnly, setCleanOverlaysOnly] = useState(false);

    // Stale-duplicate + orphan data from the Kometa assets scan. We keep the
    // raw stale list (not a pre-built rating_key map) because the cached Plex
    // rating_key drifts from the live bundle scan — matching is done below
    // against the actual bundle set by rating_key, then Plex title+year.
    const [staleItems, setStaleItems] = useState([]);
    const [orphans, setOrphans] = useState([]);

    useEffect(() => {
        const token = { cancelled: false };
        const load = async () => {
            try {
                let res = await postersAPI.scanKometaAssets();
                let data = res?.data || {};
                // Cold cache → the walk runs in a background job, not on the
                // server's event loop. Enqueue it, wait, then re-read.
                if (data.scan_required) {
                    const enq = await postersAPI.enqueueKometaAssetsScan();
                    const jobId = enq?.data?.job_id;
                    if (jobId) await pollJobUntilDone(jobId, token);
                    if (token.cancelled) return;
                    res = await postersAPI.scanKometaAssets();
                    data = res?.data || {};
                }
                if (token.cancelled) return;
                setStaleItems(data.stale || []);
                setOrphans(data.orphans || []);
            } catch {
                if (!token.cancelled) {
                    setStaleItems([]);
                    setOrphans([]);
                }
            }
        };
        load();
        return () => {
            token.cancelled = true;
        };
    }, []);

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
    // True while a background scan job is enqueued + polling (drives the
    // "Scanning…" spinner now that the walk no longer blocks the request).
    const [scanning, setScanning] = useState(false);

    // Locally-deleted variant paths since the last scan. Added to on successful
    // single/bulk delete so the UI prunes them immediately without a full
    // /by-media rescan (which walks every .bundle under /plex). Cleared by
    // refreshScan — a real scan is the source of truth.
    const [deletedPaths, setDeletedPaths] = useState(new Set());

    // Paths targeted by the currently-running cleanup job. Populated at enqueue
    // and applied to deletedPaths when the job lands `success`, so the bloat
    // counts and tiles update without forcing a 30s+ rescan.
    const pendingCleanupTargetsRef = useRef(null);

    // ---- Scan data ----
    const byMedia = useApiData({
        apiFunction: useCallback(async () => {
            // The endpoint caps `limit` at 500 and returns one page, but the
            // master-detail view needs every bundle client-side (the tabs filter
            // the full list locally). Page through `total` so large libraries
            // aren't truncated to the first 500. The scan is server-cached, so
            // follow-up pages reuse it and are cheap.
            const first = await postersAPI.listPlexMetadataByMedia({
                limit: PAGE_SIZE,
                offset: 0,
            });
            const payload = first?.data || {};
            const total = payload.total ?? (payload.bundles?.length || 0);
            const all = [...(payload.bundles || [])];
            for (let off = PAGE_SIZE; off < total; off += PAGE_SIZE) {
                const next = await postersAPI.listPlexMetadataByMedia({
                    limit: PAGE_SIZE,
                    offset: off,
                });
                all.push(...(next?.data?.bundles || []));
            }
            return { ...first, data: { ...payload, bundles: all } };
        }, []),
        dependencies: [],
        options: { showErrorToast: false, immediate: false },
    });

    const bundles = useMemo(() => {
        const raw = byMedia.data?.data?.bundles || [];
        if (deletedPaths.size === 0) return raw;
        return raw.map(b => {
            const orig = b.variants || [];
            const variants = orig.filter(v => !deletedPaths.has(v.path));
            return variants.length === orig.length ? b : { ...b, variants };
        });
    }, [byMedia.data, deletedPaths]);
    const stats = useMemo(() => {
        const raw = byMedia.data?.data?.stats || null;
        if (!raw || deletedPaths.size === 0) return raw;
        let dVariants = 0;
        let dBloat = 0;
        let dSize = 0;
        for (const b of byMedia.data?.data?.bundles || []) {
            for (const v of b.variants || []) {
                if (!deletedPaths.has(v.path)) continue;
                dVariants += 1;
                if (!v.active && (v.cls?.source || 'uploads') !== 'plex') dBloat += 1;
                dSize += v.size || 0;
            }
        }
        return {
            ...raw,
            variant_count: Math.max(0, (raw.variant_count || 0) - dVariants),
            bloat_count: Math.max(0, (raw.bloat_count || 0) - dBloat),
            bloat_size: Math.max(0, (raw.bloat_size || 0) - dSize),
        };
    }, [byMedia.data, deletedPaths]);
    // PhotoTranscoder cache is independent of the per-variant deletions tracked
    // above — it lives at <plex>/Cache/PhotoTranscoder, not inside any bundle.
    // Surface the number as a read-only stat; cleanup runs from the Plex
    // Maintenance module to avoid duplicating that operation's confirm/run UX.
    const transcoder = byMedia.data?.data?.transcoder || null;
    const loading = byMedia.isLoading;

    // On mount, read the server's cached scan — a cheap read that returns
    // scan_required + empty bundles when nothing is cached (never the ~140k-file
    // walk). So returning to the page shows the LAST scan's results immediately
    // instead of forcing a re-scan; an explicit Run scan still re-warms it.
    useEffect(() => {
        byMedia.refresh();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Reveal the results view as soon as a cached scan is present (whether from
    // the mount read above or after an explicit scan completes). Render-time
    // state sync — React's sanctioned pattern; the guard flips once so it
    // doesn't loop.
    if (!hasScanned && (byMedia.data?.data?.bundles?.length || 0) > 0) {
        setHasScanned(true);
    }

    // Build all trees once per scan payload.
    const bundleTrees = useMemo(() => {
        const m = new Map();
        for (const b of bundles) m.set(b.rating_key, buildBundleTree(b));
        return m;
    }, [bundles]);

    // Attribute each stale folder to a bundle: rating_key first, then Plex
    // title+year, then the folder's own parsed title+year. Folders that match
    // no bundle (no poster row exists, or the title isn't in Plex) are surfaced
    // separately so they aren't silently dropped.
    const { staleByRk, unmatchedStale } = useMemo(() => {
        const counts = new Map();
        const unmatched = [];
        if (!staleItems.length) return { staleByRk: counts, unmatchedStale: unmatched };
        const byRk = new Map();
        const byTY = new Map();
        for (const b of bundles) {
            byRk.set(String(b.rating_key), b);
            byTY.set(titleYearKey(b.title, b.year), b);
        }
        for (const s of staleItems) {
            let b = s.rating_key != null ? byRk.get(String(s.rating_key)) : null;
            if (!b && s.plex_title) b = byTY.get(titleYearKey(s.plex_title, s.plex_year));
            if (!b) {
                const { title, year } = parseFolderTitleYear(s.canonical || s.name);
                b = byTY.get(titleYearKey(title, year));
            }
            if (b) counts.set(b.rating_key, (counts.get(b.rating_key) || 0) + 1);
            else unmatched.push(s);
        }
        return { staleByRk: counts, unmatchedStale: unmatched };
    }, [staleItems, bundles]);

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

    // A scan now enqueues a background `plex_metadata_scan` job (the ~140k-file
    // walk runs off the server's event loop), polls it to completion, then
    // reads the freshly-warmed cache via byMedia.refresh(). `scanning` drives
    // the spinner while the job runs; the activeScanRef token cancels an
    // in-flight poll if a new scan starts or the page unmounts.
    const activeScanRef = useRef(null);
    useEffect(
        () => () => {
            if (activeScanRef.current) activeScanRef.current.cancelled = true;
        },
        []
    );

    const refreshScan = useCallback(async () => {
        if (!hasScanned) setHasScanned(true);
        setDeletedPaths(new Set());
        if (activeScanRef.current) activeScanRef.current.cancelled = true;
        const token = { cancelled: false };
        activeScanRef.current = token;
        setScanning(true);
        try {
            const res = await postersAPI.enqueuePlexMetadataScan();
            const jobId = res?.data?.job_id;
            if (jobId) await pollJobUntilDone(jobId, token);
        } catch {
            // Enqueue/poll failed — fall through and read whatever is cached.
        } finally {
            if (!token.cancelled) setScanning(false);
        }
        if (!token.cancelled) byMedia.refresh();
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
            // Bloat: when unchecked, force the harmless "nothing" mode so the
            // job skips Plex-variant deletion but can still run stale/orphan.
            body.mode = cleanBloat ? mode : 'nothing';
            body.stale_duplicates_enabled = cleanStale;
            body.orphan_assets_enabled = cleanOrphan;
            if (cleanStale) body.stale_duplicates_mode = mode;
            if (cleanOrphan) body.orphan_assets_mode = mode;
            // Overlays-only narrows the bloat pass to Kometa overlay images;
            // only meaningful when bloat is actually running.
            body.overlays_only = cleanBloat && cleanOverlaysOnly;
            const res = await postersAPI.runPlexMetadataCleanup(body);
            const jobId = res?.data?.job_id;
            if (!jobId) {
                toast.error('Failed to start cleanup');
                return;
            }
            toast.success(`${meta.label} started (job #${jobId})`);
            // Stash the targeted paths so the LiveLogModal's onCompleted hook
            // can optimistically remove them from the UI when the job succeeds.
            // Null = full-library run; we don't know what got deleted, so we
            // leave deletedPaths alone (user re-scans for a fresh count).
            pendingCleanupTargetsRef.current = body.target_paths || null;
            setLiveJobId(jobId);
            setSelectedPaths(new Set());
        } catch {
            toast.error('Failed to start cleanup');
        } finally {
            setIsEnqueuing(false);
        }
    }, [mode, cleanBloat, cleanStale, cleanOrphan, cleanOverlaysOnly, selectedPaths, toast]);

    const runCleanup = () => {
        // Report mode is the UI scan — populate tiles, don't enqueue a backend
        // job (the log dialog doesn't tail, so it adds no value over refresh).
        if (mode === 'report') {
            refreshScan();
            return;
        }
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
            setDeletedPaths(prev => {
                const next = new Set(prev);
                next.add(variant.path);
                return next;
            });
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
        const succeeded = new Set();
        let failed = 0;
        for (const path of selectedPaths) {
            try {
                await postersAPI.deletePlexMetadataVariant(path);
                succeeded.add(path);
            } catch {
                failed += 1;
            }
        }
        setBulkBusy(false);
        setSelectedPaths(new Set());
        if (succeeded.size > 0) {
            setDeletedPaths(prev => {
                const next = new Set(prev);
                for (const p of succeeded) next.add(p);
                return next;
            });
        }
        if (failed) toast.error(`Deleted ${succeeded.size}, ${failed} failed`);
        else toast.success(`Deleted ${succeeded.size} variant${succeeded.size === 1 ? '' : 's'}`);
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
    // Stale duplicates are a property of the whole media item, not a single
    // node — surface the bundle's count on any node within it.
    const staleInDetail = detail ? staleByRk.get(detail.bundle.rating_key) || 0 : 0;
    const reclaimableBytes = detail
        ? detail.variants
              .filter(v => !v.active && (v.cls?.source || 'uploads') !== 'plex')
              .reduce((s, v) => s + (v.size || 0), 0)
        : 0;
    // Subtree bloat — all bloat variants across the whole bundle tree (show +
    // seasons + episodes), used in the detail header when a show node is selected
    // to distinguish "here" (show-level) from the full subtree count.
    const subtreeBloat =
        detail && selected?.kind === 'show'
            ? (() => {
                  const tree = bundleTrees.get(detail.bundle.rating_key);
                  if (!tree) return 0;
                  return (tree.show || [])
                      .concat(
                          [...(tree.seasons.values() || [])].flatMap(s =>
                              s.posters.concat([...s.episodes.values()].flatMap(e => e.thumbs))
                          )
                      )
                      .filter(v => !v.active && (v.cls?.source || 'uploads') !== 'plex').length;
              })()
            : 0;

    return (
        <div className="flex flex-col gap-4">
            {/* Toolbar — title + mono summary stats + legend */}
            <div className="flex items-center gap-2.5 flex-wrap">
                <h1 className="font-display text-[22px] font-bold tracking-[-0.3px] text-fg m-0 mr-1.5">
                    Poster Cleanarr
                </h1>
                {hasScanned && stats ? (
                    <>
                        <span className="font-mono text-[12.5px] text-fg-muted">
                            {stats.bundle_count} items
                        </span>
                        <span className="text-fg-dim">·</span>
                        <span className="font-mono text-[12.5px] text-fg-muted">
                            {stats.variant_count} variants
                        </span>
                        <span className="text-fg-dim">·</span>
                        <span className="font-mono text-[12.5px] text-error">
                            {stats.bloat_count} bloat
                        </span>
                        <span className="text-fg-dim">·</span>
                        <span className="font-mono text-[12.5px] text-success">
                            {formatBytes(stats.bloat_size)} reclaimable
                        </span>
                        {staleItems.length > 0 && (
                            <>
                                <span className="text-fg-dim">·</span>
                                <span className="font-mono text-[12.5px] text-warning">
                                    {staleItems.length} stale duplicate
                                    {staleItems.length === 1 ? '' : 's'}
                                </span>
                            </>
                        )}
                        <span className="ml-auto flex items-center gap-3.5 font-mono text-[11px] text-fg-subtle">
                            <span className="flex items-center gap-1.5">
                                <span className="w-2 h-2 rounded-full bg-error" />
                                bloat
                            </span>
                            <span className="flex items-center gap-1.5">
                                <span className="w-2 h-2 rounded-full bg-warning" />
                                stale duplicate
                            </span>
                        </span>
                    </>
                ) : (
                    <span className="text-fg-subtle text-[13.5px]">
                        Review Plex poster variants and clean up unused (bloat) images.
                    </span>
                )}
            </div>

            {/* Transcoder + extra notes */}
            {hasScanned && stats && (
                <div className="flex flex-col gap-1 text-xs text-fg-subtle -mt-1">
                    {transcoder && transcoder.count > 0 && (
                        <div>
                            PhotoTranscoder cache:{' '}
                            <span className="font-mono text-fg-muted">
                                {transcoder.count.toLocaleString()} files ·{' '}
                                {formatBytes(transcoder.size_bytes)}
                            </span>{' '}
                            reclaimable ·{' '}
                            <Link to="/settings/modules" className="text-accent hover:underline">
                                Clean from Plex Maintenance →
                            </Link>
                        </div>
                    )}
                    {unmatchedStale.length > 0 && (
                        <div>
                            {unmatchedStale.length} stale not matched to a Plex item (see below)
                        </div>
                    )}
                    {orphans.length > 0 && <div>orphaned assets: {orphans.length} (see below)</div>}
                </div>
            )}

            {/* Global cleanup bar — Mode dropdown (all 6 cleanup modes) + a Run
                button whose label, colour, and confirm behaviour all track the
                selected mode, so the destructive options are visibly distinct. */}
            <section
                className="rounded-xl bg-surface border border-border px-4 py-3.5 flex flex-wrap items-center gap-4"
                style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
            >
                <label className="flex items-center gap-2 text-[13px] font-semibold text-fg-muted">
                    Mode
                    <select
                        value={mode}
                        onChange={e => setMode(e.target.value)}
                        className="h-[34px] bg-surface-inset border border-border rounded-lg px-3 text-[13px] font-semibold text-fg outline-none focus:border-primary cursor-pointer"
                    >
                        {Object.entries(MODE_META).map(([k, m]) => (
                            <option key={k} value={k}>
                                {m.label}
                            </option>
                        ))}
                    </select>
                </label>
                <span className="text-[12.5px] text-fg-subtle" style={{ maxWidth: '420px' }}>
                    {MODE_META[mode]?.description}
                </span>
                <div className="flex items-center gap-4">
                    <ModeCheck label="Bloat" checked={cleanBloat} onChange={setCleanBloat} />
                    <ModeCheck label="Stale" checked={cleanStale} onChange={setCleanStale} />
                    <ModeCheck label="Orphan" checked={cleanOrphan} onChange={setCleanOrphan} />
                    <ModeCheck
                        label="Overlays only"
                        checked={cleanOverlaysOnly}
                        disabled={!cleanBloat}
                        onChange={setCleanOverlaysOnly}
                        title="Limit the bloat pass to Kometa overlay images (EXIF-tagged), sparing user-uploaded customs"
                    />
                </div>
                <div className="ml-auto flex items-center gap-2">
                    {MODE_META[mode]?.scopeable && (
                        <span className="text-xs text-fg-muted">
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
                        loading={mode === 'report' ? scanning || loading : isEnqueuing}
                        loadingText={mode === 'report' ? 'Scanning…' : 'Starting…'}
                        variant={MODE_META[mode]?.variant || 'primary'}
                        onClick={runCleanup}
                        disabled={!MODE_META[mode]?.action || (mode !== 'report' && !hasScanned)}
                    >
                        {MODE_META[mode]?.action || 'No action'}
                    </LoadingButton>
                </div>
            </section>

            {/* Scan empty / loading / loaded states */}
            {!hasScanned ? (
                <div className="text-center py-16 px-6 rounded-lg border border-border-light bg-surface-alt text-sm text-fg-subtle">
                    <span className="material-symbols-outlined text-3xl mb-2 block opacity-60">
                        cleaning_services
                    </span>
                    <p className="text-fg font-medium mb-1">Ready to scan</p>
                    <p>
                        In Report mode, click <span className="font-semibold">Run scan</span> above
                        to scan Plex metadata. Walks every <code>.bundle</code> under{' '}
                        <code>/plex</code>; can take a minute on large libraries.
                    </p>
                </div>
            ) : byMedia.error ? (
                <div className="text-center py-16 px-6 rounded-lg border border-error/40 bg-error/10 text-error text-sm">
                    Couldn&apos;t read Plex metadata:{' '}
                    {byMedia.error?.message || String(byMedia.error)}.
                </div>
            ) : (scanning || loading) && bundles.length === 0 ? (
                <Spinner size="medium" text="Scanning Plex metadata..." center />
            ) : bundles.length === 0 ? (
                <div className="text-center py-16 text-fg-subtle">
                    No poster variants found. Plex metadata looks clean.
                </div>
            ) : (
                <>
                    {/* ---- Master-detail split ---- */}
                    {/* On mobile we collapse to a single column and toggle which pane
                    is visible based on selection; on desktop both panes render
                    side-by-side as before. Internal scroll containers are still
                    present on mobile but become no-ops because the grid has no
                    minHeight there — the page scrolls naturally instead. */}
                    <section
                        className="rounded-xl border border-border overflow-hidden bg-surface"
                        style={{ boxShadow: '0 2px 16px -8px rgba(0,0,0,.6)' }}
                    >
                        <div
                            className="grid"
                            style={{
                                gridTemplateColumns: isMobile ? '1fr' : '560px 1fr',
                                // Cap the panel near the viewport so a long media
                                // list scrolls inside its own pane instead of the
                                // whole page growing to fit it. The report header
                                // above can still scroll away. The single
                                // minmax(0, 1fr) row is what actually constrains the
                                // columns to that height — a bare max-height would
                                // just clip the list instead of letting it scroll.
                                gridTemplateRows: isMobile ? undefined : 'minmax(0, 1fr)',
                                maxHeight: isMobile ? undefined : 'calc(100vh - 150px)',
                            }}
                        >
                            {/* Left pane — hidden on mobile when a node is selected */}
                            {(!isMobile || !selected) && (
                                <div
                                    className={`flex flex-col min-h-0 overflow-hidden ${
                                        isMobile ? '' : 'border-r border-border'
                                    }`}
                                >
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
                                                className={`flex-1 px-2 py-[7px] text-xs rounded-[7px] cursor-pointer border transition-colors ${
                                                    tab === v
                                                        ? 'bg-primary text-on-color border-transparent font-semibold'
                                                        : 'bg-transparent text-fg-muted border-transparent hover:bg-row-hover'
                                                }`}
                                            >
                                                {label}
                                            </button>
                                        ))}
                                    </div>
                                    <div className="m-2 flex items-center gap-2 h-9 px-3 rounded-lg bg-surface-inset border border-border focus-within:border-primary transition-colors">
                                        <span className="material-symbols-outlined text-[16px] text-fg-subtle">
                                            search
                                        </span>
                                        <input
                                            type="search"
                                            value={search}
                                            onChange={e => setSearch(e.target.value)}
                                            placeholder="Search titles…"
                                            className="flex-1 min-w-0 bg-transparent border-0 outline-none text-[12.5px] text-fg placeholder:text-fg-dim"
                                        />
                                    </div>
                                    {/* Tree list */}
                                    <div className="overflow-y-auto flex-1">
                                        {filteredBundles.length === 0 ? (
                                            <div className="text-center text-fg-subtle text-sm p-4">
                                                No matches
                                            </div>
                                        ) : (
                                            filteredBundles.map(bundle => (
                                                <BundleTreeRow
                                                    key={bundle.bundle_path}
                                                    bundle={bundle}
                                                    tree={bundleTrees.get(bundle.rating_key)}
                                                    selected={selected}
                                                    expandedShows={expandedShows}
                                                    expandedSeasons={expandedSeasons}
                                                    onToggleShow={toggleShow}
                                                    onToggleSeason={toggleSeason}
                                                    onSelect={selectNode}
                                                    staleCount={
                                                        staleByRk.get(bundle.rating_key) || 0
                                                    }
                                                />
                                            ))
                                        )}
                                    </div>
                                </div>
                            )}
                            {/* Right pane — on mobile, only rendered when a node is selected */}
                            {(!isMobile || selected) && (
                                <div className="flex flex-col min-w-0 min-h-0">
                                    {!detail ? (
                                        <div className="p-12 text-center text-fg-subtle">
                                            Select an item on the left. Shows have chevrons to drill
                                            into seasons and episodes.
                                        </div>
                                    ) : (
                                        <>
                                            <header className="p-4 border-b border-border">
                                                {isMobile && (
                                                    <button
                                                        type="button"
                                                        onClick={() => selectNode(null)}
                                                        className="mb-2 text-sm text-fg cursor-pointer inline-flex items-center gap-1 hover:underline"
                                                    >
                                                        ← Back to list
                                                    </button>
                                                )}
                                                <div className="text-xs text-fg-muted mb-1 flex items-center gap-2">
                                                    {detail.breadcrumb.map((crumb, i) => (
                                                        <React.Fragment key={i}>
                                                            {i > 0 && (
                                                                <span className="text-fg-subtle">
                                                                    ›
                                                                </span>
                                                            )}
                                                            <span
                                                                className={
                                                                    i < detail.breadcrumb.length - 1
                                                                        ? 'cursor-pointer hover:text-fg'
                                                                        : ''
                                                                }
                                                                onClick={() => {
                                                                    if (
                                                                        i >=
                                                                        detail.breadcrumb.length - 1
                                                                    )
                                                                        return;
                                                                    if (i === 0)
                                                                        selectNode({
                                                                            kind: 'show',
                                                                            ratingKey:
                                                                                detail.bundle
                                                                                    .rating_key,
                                                                        });
                                                                    else if (i === 1)
                                                                        selectNode({
                                                                            kind: 'season',
                                                                            ratingKey:
                                                                                detail.bundle
                                                                                    .rating_key,
                                                                            season: selected.season,
                                                                        });
                                                                }}
                                                            >
                                                                {crumb}
                                                            </span>
                                                        </React.Fragment>
                                                    ))}
                                                </div>
                                                <h3 className="font-display text-[19px] font-semibold text-fg m-0">
                                                    {
                                                        detail.breadcrumb[
                                                            detail.breadcrumb.length - 1
                                                        ]
                                                    }
                                                </h3>
                                                <div className="font-mono text-[12px] text-fg-muted mt-1.5">
                                                    {detail.variants.length} variants ·{' '}
                                                    <span className="text-success">
                                                        {activeInDetail} active
                                                    </span>{' '}
                                                    ·{' '}
                                                    <span className="text-error">
                                                        {bloatInDetail} bloat here
                                                    </span>
                                                    {staleInDetail > 0 && (
                                                        <>
                                                            {' '}
                                                            ·{' '}
                                                            <span style={{ color: '#f59e0b' }}>
                                                                {staleInDetail} stale duplicate
                                                                {staleInDetail === 1 ? '' : 's'}
                                                            </span>
                                                        </>
                                                    )}
                                                    {selected?.kind === 'show' &&
                                                        subtreeBloat > bloatInDetail && (
                                                            <>
                                                                {' '}
                                                                ·{' '}
                                                                <span className="text-fg-subtle">
                                                                    {subtreeBloat} in subtree
                                                                </span>
                                                            </>
                                                        )}
                                                    {plexInDetail > 0 && (
                                                        <>
                                                            {' '}
                                                            ·{' '}
                                                            <span className="text-fg-subtle">
                                                                {plexInDetail} plex
                                                            </span>
                                                        </>
                                                    )}
                                                    {bloatInDetail > 0 && (
                                                        <>
                                                            {' '}
                                                            · {formatBytes(reclaimableBytes)}{' '}
                                                            reclaimable
                                                        </>
                                                    )}
                                                </div>
                                            </header>
                                            <div className="flex-1 overflow-y-auto p-4">
                                                {detail.variants.length === 0 ? (
                                                    <div className="text-center text-fg-subtle py-12">
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
                                                    <span className="text-xs text-fg-muted mr-auto">
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
                            )}
                        </div>
                    </section>

                    {unmatchedStale.length > 0 && (
                        <section className="rounded-lg border border-border bg-surface mt-4 p-4">
                            <div className="flex items-center gap-2 mb-3">
                                <h2 className="text-sm font-semibold text-fg">
                                    Stale duplicates without a Plex poster row
                                </h2>
                                <span style={typeBadge}>{unmatchedStale.length}</span>
                                <span className="text-fg-subtle text-xs">
                                    Renamed asset folders whose title isn&apos;t in the Plex bundle
                                    scan — still cleaned by the Stale pass
                                </span>
                            </div>
                            <div className="overflow-y-auto" style={{ maxHeight: '320px' }}>
                                {unmatchedStale.map(s => (
                                    <div
                                        key={s.folder || s.name}
                                        className="flex items-center justify-between gap-2 py-1.5 border-b border-border text-sm"
                                    >
                                        <span className="truncate text-fg-muted">
                                            <span style={stalePill}>⧉</span> {s.name}
                                            <span className="text-fg-subtle"> → {s.canonical}</span>
                                        </span>
                                        <span className="text-fg-subtle text-xs whitespace-nowrap">
                                            {formatBytes(s.size)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}

                    {orphans.length > 0 && (
                        <section className="rounded-lg border border-border bg-surface mt-4 p-4">
                            <div className="flex items-center gap-2 mb-3">
                                <h2 className="text-sm font-semibold text-fg">Orphaned assets</h2>
                                <span style={typeBadge}>{orphans.length}</span>
                                <span className="text-fg-subtle text-xs">
                                    Kometa assets with no matching media in your library
                                </span>
                            </div>
                            <div className="overflow-y-auto" style={{ maxHeight: '320px' }}>
                                {orphans.map(o => (
                                    <div
                                        key={o.path}
                                        className="flex items-center justify-between gap-2 py-1.5 border-b border-border text-sm"
                                    >
                                        <span className="truncate text-fg-muted">{o.path}</span>
                                        <span className="text-fg-subtle text-xs whitespace-nowrap">
                                            {formatBytes(o.size)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}
                </>
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
            <LiveLogModal
                jobId={liveJobId}
                onClose={() => setLiveJobId(null)}
                onCompleted={(_jobId, jobStatus) => {
                    if (jobStatus !== 'success') {
                        pendingCleanupTargetsRef.current = null;
                        return;
                    }
                    const targets = pendingCleanupTargetsRef.current;
                    pendingCleanupTargetsRef.current = null;
                    if (!targets || targets.length === 0) return;
                    setDeletedPaths(prev => {
                        const next = new Set(prev);
                        for (const p of targets) next.add(p);
                        return next;
                    });
                }}
            />
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
const stalePill = {
    padding: '1px 6px',
    borderRadius: '9999px',
    background: 'rgba(245,158,11,0.2)',
    color: '#f59e0b',
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
    staleCount = 0,
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
                    <div className="flex items-center gap-2 text-sm font-medium text-fg">
                        <span className="truncate">
                            {bundle.title || '(unknown)'}
                            {bundle.year ? ` (${bundle.year})` : ''}
                        </span>
                        <span style={typeBadge}>{bundle.metadata_type_label}</span>
                    </div>
                    <div
                        className="text-fg-muted flex items-center gap-2"
                        style={{ fontSize: '11px' }}
                    >
                        <span className="truncate">
                            {bundle.library_name || ''} · {bundle.variants.length} variants
                        </span>
                        {bloatCount > 0 && <span style={bloatPill}>● {bloatCount}</span>}
                        {staleCount > 0 && (
                            <span style={stalePill} title="Stale duplicate asset folder">
                                ⧉ {staleCount}
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
                                            className="flex-1 min-w-0 text-fg"
                                            style={{ fontSize: '13px' }}
                                        >
                                            Season {season.n}
                                            <span
                                                className="text-fg-muted ml-2"
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
                                                            className="flex-1 min-w-0 text-fg"
                                                            style={{ fontSize: '12px' }}
                                                        >
                                                            Episode {episode.n}
                                                            <span
                                                                className="text-fg-muted ml-2"
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
